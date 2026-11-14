"""Public audio behavior locked before extracting the production module."""
from copy import copy, deepcopy

import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


class RecordingVoice:
    def __init__(self, label='voice', error=None):
        self.label, self.error, self.calls = label, error, []

    async def generate(self, shot_id, speaker_id, text):
        self.calls.append((shot_id, speaker_id, text))
        if self.error:
            raise RuntimeError(self.error)
        return {'id': f'{self.label}-{len(self.calls)}', 'shotId': shot_id,
                'durationMs': 1200, 'text': text}


class RecordingLipSync:
    def __init__(self, label='lip', error=None):
        self.label, self.error, self.calls = label, error, []

    async def generate(self, shot_id, audio, dialogue):
        self.calls.append((shot_id, deepcopy(audio), deepcopy(dialogue)))
        if self.error:
            raise RuntimeError(self.error)
        return {'id': f'{self.label}-{len(self.calls)}', 'shotId': shot_id,
                'startMs': 0, 'endMs': audio['durationMs']}


async def prepared():
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜里，姐妹两人在车站相遇。',
        duration_sec=30, mode='import_story',
    ))
    pid = created['project']['id']
    record = await pipeline._repository.get(pid)
    record.project.update({
        'script': {'shots': [{'id': 's1', 'durationSec': 5, 'characterIds': ['sister'],
                              'dialogue': '你终于来了。', 'narration': '雨声渐弱。'}]},
        'visualAssets': [{'id': 'visual', 'shotId': 's1', 'valid': True,
                          'provider': 'mock', 'mediaType': 'video'}],
        'audioAssets': [{'id': 'old-audio', 'shotId': 's1', 'durationMs': 1500, 'valid': True}],
        'lipSyncAssets': [{'id': 'old-lip', 'shotId': 's1', 'valid': True},
                          {'id': 'other-lip', 'shotId': 's2', 'valid': True}],
        'timelines': {'s1': {'visualAssetId': 'visual', 'marker': 'previous'},
                      's2': {'marker': 'unrelated'}},
        'exportManifest': {'files': ['old.mp4']},
    })
    await pipeline._repository.save(record)
    voice, lip = RecordingVoice(), RecordingLipSync()
    pipeline._tts_provider, pipeline._lip_sync_provider = voice, lip
    return runtime, pid, voice, lip


async def test_audio_uses_current_providers_on_request_copy_and_later_calls():
    runtime, pid, first_voice, first_lip = await prepared()
    pipeline = runtime.pipeline
    result = await pipeline.generate_shot_audio(pid, 's1', expected_version=1)
    assert result['asset']['text'] == '你终于来了。'  # Dialogue still takes priority.
    scoped = copy(pipeline)
    second_voice, second_lip = RecordingVoice('second'), RecordingLipSync('second')
    scoped._tts_provider, scoped._lip_sync_provider = second_voice, second_lip
    result = await scoped.generate_shot_audio(pid, 's1', expected_version=1)
    assert result['asset']['id'] == 'second-1'
    assert result['lipSync']['id'] == 'second-1'
    # Replacing dependencies after earlier calls must not leave a cached module behind.
    third_voice, third_lip = RecordingVoice('third'), RecordingLipSync('third')
    pipeline._tts_provider, pipeline._lip_sync_provider = third_voice, third_lip
    result = await pipeline.generate_shot_audio(pid, 's1', expected_version=1)
    assert result['asset']['id'] == 'third-1'
    assert first_voice.calls == second_voice.calls == third_voice.calls == [
        ('s1', 'sister', '你终于来了。'),
    ]
    assert len(first_lip.calls) == len(second_lip.calls) == len(third_lip.calls) == 1
    record = await pipeline._repository.get(pid)
    assert [a['id'] for a in record.project['audioAssets'] if a['valid']] == ['third-1']
    assert record.project['timelines']['s2'] == {'marker': 'unrelated'}


async def test_lipsync_regeneration_reuses_voice_and_only_replaces_its_own_assets():
    runtime, pid, voice, lip = await prepared()
    before = await runtime.pipeline._repository.get(pid)
    result = await runtime.pipeline.regenerate_shot(pid, 's1', scope='lipsync', expected_version=1)
    after = await runtime.pipeline._repository.get(pid)
    assert voice.calls == []
    assert len(lip.calls) == 1
    assert lip.calls[0][1] == before.project['audioAssets'][0]
    assert lip.calls[0][2]['text'] == '你终于来了。'
    assert result['scope'] == 'lipsync'
    assert result['asset'] == before.project['audioAssets'][0]
    assert after.project['audioAssets'] == before.project['audioAssets']
    assert after.project['visualAssets'] == before.project['visualAssets']
    assert after.project['lipSyncAssets'][0]['valid'] is False
    assert after.project['lipSyncAssets'][1] == before.project['lipSyncAssets'][1]
    assert after.project['timelines']['s2'] == before.project['timelines']['s2']
    assert after.project['timelines']['s1']['lipSyncTrack'][0]['assetId'] == result['lipSync']['id']
    assert after.project['exportManifest'] is None
    assert after.project['downstreamInvalidated'] is True


async def test_lipsync_failure_keeps_previous_assets_and_error_without_retry():
    runtime, pid, voice, _ = await prepared()
    lip = RecordingLipSync(error='PROVIDER_RATE_LIMITED')
    runtime.pipeline._lip_sync_provider = lip
    before = await runtime.pipeline._repository.get(pid)
    with pytest.raises(RuntimeError, match='PROVIDER_RATE_LIMITED'):
        await runtime.pipeline.regenerate_shot(pid, 's1', scope='lipsync', expected_version=1)
    assert len(lip.calls) == 1 and voice.calls == []
    assert await runtime.pipeline._repository.get(pid) == before


@pytest.mark.parametrize('scope', ['audio', 'lipsync'])
async def test_no_spoken_text_does_not_call_models(scope):
    runtime, pid, voice, lip = await prepared()
    record = await runtime.pipeline._repository.get(pid)
    shot = record.project['script']['shots'][0]
    shot['dialogue'] = ''
    shot['narration'] = '只有旁白。' if scope == 'lipsync' else ''
    await runtime.pipeline._repository.save(record)
    before = await runtime.pipeline._repository.get(pid)
    result = await runtime.pipeline.regenerate_shot(pid, 's1', scope=scope, expected_version=1)
    assert result['asset'] is None and result['lipSync'] is None
    assert voice.calls == lip.calls == []
    if scope == 'lipsync':
        assert await runtime.pipeline._repository.get(pid) == before
        assert result['timeline'] == before.project['timelines']['s1']
    else:
        assert result['timeline']['visualAssetId'] == 'visual'
        assert result['timeline']['dialogue'] == []


@pytest.mark.parametrize('stage', ['tts', 'lip_sync'])
async def test_audio_http_keeps_access_version_and_failure_stage_without_writes(stage):
    runtime, pid, voice, lip = await prepared()
    await runtime.pipeline.claim_project(pid, user_id='owner')
    if stage == 'tts':
        voice.error = 'PROVIDER_UNAVAILABLE'
    else:
        lip.error = 'PROVIDER_UNAVAILABLE'
    before = await runtime.pipeline._repository.get(pid)
    async with AsyncClient(transport=ASGITransport(app=create_app(runtime)),
                           base_url='http://test') as client:
        path = f'/api/projects/{pid}/shots/s1/audio'
        denied = await client.post(path, json={'expectedVersion': 1},
                                   headers={'X-User-Id': 'other'})
        assert denied.status_code == 403
        conflict = await client.post(path, json={'expectedVersion': 0},
                                     headers={'X-User-Id': 'owner'})
        assert conflict.status_code == 409
        assert conflict.json()['error'] == 'VERSION_CONFLICT'
        assert voice.calls == lip.calls == []
        failure = await client.post(path, json={'expectedVersion': 1},
                                    headers={'X-User-Id': 'owner'})
        assert failure.status_code == 503
        assert failure.json()['error'] == 'PROVIDER_UNAVAILABLE'
        assert failure.json()['stage'] == stage
    assert len(voice.calls) == 1 and len(lip.calls) == (stage == 'lip_sync')
    assert await runtime.pipeline._repository.get(pid) == before
