import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.minimax_h3 import MinimaxH3Provider

RULES = Path(__file__).resolve().parents[2] / 'skills/h3-prompt-writing'


@pytest.fixture
async def setup():
    runtime = create_memory_runtime()
    p = runtime.pipeline
    created = await p.create_project(CreateProject(
        input_type='story', story='雨夜，女子推门走进便利店寻找朋友。',
        duration_sec=30, mode='import_story'))
    pid = created['project']['id']
    record = await p._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{
        'id': 'sh1', 'durationSec': 5, 'characterIds': [], 'title': '推门',
        'visualDescription': '女子走进便利店', 'action': '推门进入',
        'actionAfter': '双脚进入室内，门在身后', 'dialogue': '你终于来了。',
        'resolution': '2K', 'aspectRatio': '9:16',
    }]}
    await p._repository.save(record)
    calls = []

    async def transport(request):
        calls.append(request)
        raise AssertionError('Preflight must not contact models')

    p._dynamic_visual_provider = MinimaxH3Provider(
        api_key='secret-never-show', prompt_mode='context-ir',
        transport=httpx.MockTransport(transport))
    return runtime, pid, record.project['version'], calls


async def test_preflight_is_read_only_accurate_and_never_calls_models(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    before = deepcopy((await p._repository.get(pid)).project)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        response = await client.post(f'/api/projects/{pid}/shots/sh1/visual/preflight',
                                     json={'expectedVersion': version})
    assert response.status_code == 200
    body = response.json()
    assert body['parameters']['resolution'] == '768P'
    assert body['model'] == 'MiniMax-H3'
    assert body['prompt']['kind'] == 'submission'
    assert '你终于来了。' in body['prompt']['text']
    assert body['calls'] == {'text': 0, 'video': 1}
    assert body['price'] is None
    assert body['ready'] is True
    assert len(body['fingerprint']) == 64
    assert 'secret-never-show' not in response.text
    assert calls == []
    assert (await p._repository.get(pid)).project == before


async def test_stale_model_or_shot_preflight_blocks_before_call(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    preview = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    p._dynamic_visual_provider._resolution = '1080P'
    with pytest.raises(DomainError, match='PREFLIGHT_STALE'):
        await p.generate_shot_visual(pid, 'sh1', expected_version=version,
                                     preflight_fingerprint=preview['fingerprint'])
    assert calls == []


async def test_invalid_duration_blocks_preview_and_legacy_submission(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['script']['shots'][0]['durationSec'] = 30
    await p._repository.save(record)
    preview = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert not preview['ready'] and preview['errors']
    with pytest.raises(DomainError):
        await p.generate_shot_visual(pid, 'sh1', expected_version=version)
    assert calls == []


async def test_long_narration_blocks_queue_and_legacy_before_any_call(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['script']['shots'][0].update(dialogue='', narration='雨' * 56)
    await p._repository.save(record)
    preview = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert not preview['ready'] and preview['errors'] == ['VIDEO_SPEECH_OVER_BUDGET']
    assert preview['speechReview']['estimatedSpeechSec'] == 11.2
    assert preview['speech']['narration'] == '雨' * 56
    for call in (p.generate_shot_visual(pid, 'sh1', expected_version=version),
                 p.request_video_job(pid, 'sh1', expected_version=version, operation_id='long')):
        with pytest.raises(DomainError, match='VIDEO_SPEECH_OVER_BUDGET'):
            await call
    assert calls == [] and await p.list_video_jobs(pid) == []


async def test_preparation_discloses_scene_and_camera_without_rewriting(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['script']['shots'][0].update(
        visualDescription='车厢内朝车门的固定斜侧机位', cameraMovement='固定镜头',
        actionBefore='林夏站在车外', actionMiddle='登阶跨过门槛并向过道走一步',
        actionAfter='身体双脚均在车内，车门关闭')
    await p._repository.save(record)
    preview = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert any('未提供场景参考' in warning for warning in preview['warnings'])
    assert preview['camera']['cameraMovement'] == '固定镜头'
    prompt = preview['prompt']['text']
    assert prompt.count('车厢内朝车门的固定斜侧机位') == 1
    assert prompt.count('登阶跨过门槛并向过道走一步') == 1
    assert '不复制人物参考图的机位和站姿' in prompt
    assert calls == []


async def test_actual_context_ir_request_matches_preflight(setup):
    runtime, pid, version, _ = setup
    p = runtime.pipeline
    submitted = []

    def handler(request):
        if request.method == 'POST':
            submitted.append(json.loads(request.content))
            return httpx.Response(200, json={'task_id': 'offline-task'})
        if '/query/' in request.url.path:
            return httpx.Response(200, json={'task': {
                'status': 'succeeded', 'content': {'url': 'https://offline.invalid/video.mp4'},
            }})
        return httpx.Response(200, content=b'fake-video')

    p._dynamic_visual_provider._transport = httpx.MockTransport(handler)
    preflight = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    result = await p.generate_shot_visual(pid, 'sh1', expected_version=version,
                                         preflight_fingerprint=preflight['fingerprint'])
    assert len(submitted) == 1
    assert submitted[0]['content'][0]['text'] == preflight['prompt']['text']
    for key in ('resolution', 'duration', 'ratio'):
        assert submitted[0][key] == preflight['parameters'][key]
    assert result['asset']['preflightFingerprint'] == preflight['fingerprint']
    assert result['asset']['requestedParameters']['resolution'] == '768P'


async def test_skill_input_is_shared_with_writer_and_rules_changes_invalidate(setup, tmp_path):
    from shutil import copytree

    from comicflow.providers.h3_skill import H3SkillPromptWriter
    from test_h3_skill_execution import valid_rewrite

    runtime, pid, version, calls = setup
    p = runtime.pipeline
    copytree(RULES, tmp_path / 'skill')
    inputs = []

    async def complete(system, user):
        inputs.append((system, user))
        return await valid_rewrite(system, user)

    writer = H3SkillPromptWriter(complete, skill_dir=tmp_path / 'skill')
    p._dynamic_visual_provider._prompt_mode = 'local-skill'
    p._dynamic_visual_provider.set_prompt_writer(writer)
    prepared = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert prepared['ready']
    assert prepared['prompt']['kind'] == 'expansion-input'
    assert prepared['calls'] == {'text': 1, 'video': 1}
    assert inputs == calls == []
    _, shot, characters, _ = await p._prepare_shot_visual(pid, 'sh1', expected_version=version)
    await writer.write(shot, characters)
    from comicflow.production.visual_preflight import display
    assert display(inputs[0][0]) == prepared['prompt']['system']
    assert display(inputs[0][1]) == prepared['prompt']['text']
    path = tmp_path / 'skill/SKILL.md'
    changed_rules = path.read_text(encoding='utf-8') + '\nRule version changed.\n'
    path.write_text(changed_rules, encoding='utf-8')
    changed = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert changed['fingerprint'] != prepared['fingerprint']
    with pytest.raises(DomainError, match='PREFLIGHT_STALE'):
        await p.generate_shot_visual(pid, 'sh1', expected_version=version,
                                     preflight_fingerprint=prepared['fingerprint'])
    assert calls == [] and len(inputs) == 1


async def add_reference_scene(p, pid):
    card = {'id': 'c1', 'name': '女子', 'appearance': '短发', 'clothing': '蓝衣',
            'personality': '沉稳', 'voice': {}, 'revision': 1,
            'referenceBoard': {'id': 'board1', 'objectKey': 'board.png'}}
    await p._character_repository.save(card)
    record = await p._repository.get(pid)
    record.project['script']['shots'].insert(0, {'id': 'previous', 'durationSec': 5})
    record.project['script']['shots'][-1]['characterIds'] = ['c1']
    record.project['script']['scenes'] = [{'id': 'scene1', 'shotIds': ['previous', 'sh1'],
                                         'backgroundImageObjectKey': 'scene.png'}]
    record.project['visualAssets'] = [{'id': 'old', 'shotId': 'previous', 'valid': True,
                                      'lastFrameObjectKey': 'tail.png'}]
    await p._repository.save(record)
    return card


async def test_reference_order_signatures_and_asset_freshness(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    card = await add_reference_scene(p, pid)

    class Store:
        signature = 1
        missing = False

        async def presigned_get_url(self, key, expires_in=900):
            return f'https://assets.test/{key}?signature={self.signature}'

        async def exists(self, key):
            return not self.missing

    store = Store()
    p._asset_store = store
    first = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert first['ready']
    assert [r['view'] for r in first['references']] == [
        'reference-board', 'continuity-anchor', 'scene-anchor']
    assert first['mode'] == 'ref2va'
    assert 'signature' not in json.dumps(first)
    store.signature = 2
    p._presigned_url_cache.clear()
    second = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert first['fingerprint'] == second['fingerprint']
    card['revision'] = 2
    await p._character_repository.save(card)
    changed = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert changed['fingerprint'] != second['fingerprint']
    store.missing = True
    missing = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert missing['errors'] == ['REFERENCE_FILE_MISSING']
    with pytest.raises(DomainError, match='REFERENCE_FILE_MISSING'):
        await p.generate_shot_visual(pid, 'sh1', expected_version=version)
    assert calls == []


@pytest.mark.parametrize('case,code', [
    ('limit', 'H3_REFERENCE_LIMIT'), ('conflict', 'H3_REFERENCE_MODE_CONFLICT'),
    ('length', 'VIDEO_PROMPT_TOO_LONG'), ('local', 'H3_REFERENCE_UNREACHABLE'),
])
async def test_invalid_input_is_local_and_never_submits(setup, case, code):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    record = await p._repository.get(pid)
    shot = record.project['script']['shots'][0]
    if case == 'limit':
        shot['referenceImages'] = [{'url': f'https://assets.test/{i}.png'} for i in range(10)]
    elif case == 'conflict':
        shot['firstFrameUrl'] = 'https://assets.test/first.png'
        shot['referenceImages'] = [{'url': 'https://assets.test/ref.png'}]
    elif case == 'local':
        shot['firstFrameUrl'] = 'http://127.0.0.1/frame.png'
    else:
        shot['dialogue'] = '很长的对白' * 2000
    await p._repository.save(record)
    preview = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert not preview['ready'] and preview['errors'] == [code]
    with pytest.raises(DomainError, match=code):
        await p.generate_shot_visual(pid, 'sh1', expected_version=version)
    assert calls == []


async def test_preflight_access_and_version_checks(setup):
    runtime, pid, version, calls = setup
    record = await runtime.pipeline._repository.get(pid)
    record.project['ownerUserId'] = 'alice'
    await runtime.pipeline._repository.save(record)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        url = f'/api/projects/{pid}/shots/sh1/visual/preflight'
        denied = await client.post(url, headers={'X-User-Id': 'bob'},
                                   json={'expectedVersion': version})
        assert denied.status_code == 403
        stale = await client.post(url, headers={'X-User-Id': 'alice'},
                                  json={'expectedVersion': version + 1})
        assert stale.status_code == 409
    assert calls == []


async def test_wan_preview_shares_request_and_validates_duration(setup):
    from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    wan = BailianImageToVideoProvider(api_key='offline', model='wan2.2-t2v-plus',
                                     generation_type='t2v', resolution='720P')
    p._dynamic_visual_provider = wan
    preview = await p.preview_shot_visual(pid, 'sh1', expected_version=version)
    _, shot, cards, _ = await p._prepare_shot_visual(pid, 'sh1', expected_version=version)
    request = wan._request(shot, cards)
    assert preview['parameters'] == request['parameters']
    assert preview['parameters']['size'] == '720*1280'
    assert preview['prompt']['text'] == request['input']['prompt']
    assert preview['calls']['text'] == 0 and calls == []


async def test_unknown_adapter_cannot_skip_preflight(setup):
    runtime, pid, version, calls = setup

    class Unsupported:
        async def generate(self, shot, characters):
            calls.append('unexpected')

    runtime.pipeline._dynamic_visual_provider = Unsupported()
    preview = await runtime.pipeline.preview_shot_visual(pid, 'sh1', expected_version=version)
    assert preview['errors'] == ['VIDEO_PREFLIGHT_UNSUPPORTED']
    with pytest.raises(DomainError, match='VIDEO_PREFLIGHT_UNSUPPORTED'):
        await runtime.pipeline.generate_shot_visual(pid, 'sh1', expected_version=version)
    assert calls == []


async def test_shared_guard_blocks_regeneration_and_worker_session(setup):
    runtime, pid, version, calls = setup
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['script']['shots'][0]['durationSec'] = 30
    record.project['stage'] = 'storyboard-ready'
    record.project['generationSession'] = {'id': 'session', 'status': 'ready', 'mode': 'automatic'}
    await p._repository.save(record)
    with pytest.raises(DomainError, match='H3_DURATION_INVALID'):
        await p.regenerate_shot(pid, 'sh1', scope='shot', expected_version=version)
    session = await p.advance_generation_session(pid)
    assert session['status'] == 'waiting-retry'
    assert session['lastError'] == 'H3_DURATION_INVALID'
    assert calls == []


async def test_current_registry_revision_and_model_are_used_on_both_routes(setup):
    runtime, pid, version, calls = setup
    registry = runtime.model_registry
    view = await registry.mutate('connection', None, {
        'revision': 0, 'name': 'offline', 'baseUrl': 'https://offline.invalid',
        'apiKey': 'registry-secret',
    })
    connection_id = view['connections'][0]['id']
    view = await registry.mutate('model', None, {
        'revision': view['revision'], 'name': 'H3', 'connectionId': connection_id,
        'protocol': 'compshare-h3', 'model': 'MiniMax-H3', 'enabled': True,
        'config': {'resolution': '768P', 'h3PromptMode': 'context-ir'},
    })
    model_id = view['models'][0]['id']
    view = await registry.bind({'revision': view['revision'], 'bindings': {'video': model_id}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        url = f'/api/projects/{pid}/shots/sh1/visual'
        preflight = (await client.post(url + '/preflight',
                                       json={'expectedVersion': version})).json()
        assert preflight['modelConfigRevision'] == view['revision']
        assert preflight['parameters']['resolution'] == '768P'
        view = await registry.mutate('model', model_id, {
            'revision': view['revision'], 'name': 'H3', 'connectionId': connection_id,
            'protocol': 'compshare-h3', 'model': 'MiniMax-H3', 'enabled': True,
            'config': {'resolution': '1080P', 'h3PromptMode': 'context-ir'},
        })
        response = await client.post(url, json={'expectedVersion': version,
                                    'preflightFingerprint': preflight['fingerprint']})
        assert response.status_code == 409
        assert response.json()['error'] == 'PREFLIGHT_STALE'
        fresh = (await client.post(url + '/preflight',
                                   json={'expectedVersion': version})).json()
        assert fresh['parameters']['resolution'] == '1080P'
        assert 'registry-secret' not in json.dumps(fresh)
    assert calls == []
