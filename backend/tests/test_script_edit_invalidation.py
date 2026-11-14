"""Editing a saved shot must not leave its old footage usable as continuity input."""
from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.minimax_h3 import MinimaxH3Provider


@pytest.mark.parametrize('confirmed', [False, True])
async def test_script_edit_invalidates_old_video_and_blocks_its_tail(confirmed):
    runtime = create_memory_runtime()
    p = runtime.pipeline
    initial = await p.create_project(CreateProject(
        input_type='story', story='林夏上车，随后坐下。', duration_sec=30, mode='import_story'))
    pid = initial['project']['id']
    record = await p._repository.get(pid)
    record.project['script'] = {
        'title': '雨夜公交',
        'shots': [{'id': 's1', 'durationSec': 5, 'narration': '上车。'},
                  {'id': 's2', 'durationSec': 5, 'narration': '坐下。'}],
        'scenes': [{'id': 'scene', 'shotIds': ['s1', 's2']}],
    }
    record.project['visualAssets'] = [{'id': 'old-video', 'shotId': 's1', 'valid': True,
        'objectKey': 'old.mp4', 'lastFrameObjectKey': 'old-tail.jpg', 'mediaType': 'video'}]
    if confirmed:
        record.project['scriptConfirmedVersion'] = record.project['version']
    await p._repository.save(record)

    def forbidden(request):
        pytest.fail('Saving or previewing a script must never submit a provider request')

    p.set_video_provider(MinimaxH3Provider(api_key='offline-only', prompt_mode='context-ir',
                                         transport=httpx.MockTransport(forbidden)))
    draft = deepcopy(record.project['script'])
    draft['shots'][0]['narration'] = '林夏赶上末班车。'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                 base_url='http://test') as client:
        changed = await client.patch(f'/api/projects/{pid}/script',
            json={'expectedVersion': record.project['version'], 'script': draft})
        assert changed.status_code == 200, changed.text
        saved = (await client.get(f'/api/projects/{pid}')).json()
        old = saved['visualAssets'][0]
        assert old['valid'] is False, 'Edited shot still treats old footage as current'
        assert old['objectKey'] == 'old.mp4' and old['lastFrameObjectKey'] == 'old-tail.jpg'
        assert saved['project']['scriptVersions'][-1]['script'] == record.project['script']
        assert saved['project'].get('scriptConfirmedVersion') is None
        assert saved['project']['downstreamInvalidated'] is True
        preview = await client.post(f'/api/projects/{pid}/shots/s2/visual/preflight',
            json={'expectedVersion': saved['project']['version']})
        assert preview.status_code == 200, preview.text
        assert preview.json()['errors'] == ['CASCADE_FRAME_MISSING']


@pytest.mark.parametrize('change', ['shot', 'scene', 'none'])
async def test_script_save_retains_unaffected_media_and_invalidates_known_dependents(change):
    p = create_memory_runtime().pipeline
    initial = await p.create_project(CreateProject(
        input_type='story', story='林夏在雨夜上车，随后坐下。',
        duration_sec=30, mode='import_story'))
    pid = initial['project']['id']
    record = await p._repository.get(pid)
    script = {'shots': [{'id': sid, 'narration': '原旁白'} for sid in ['s1', 's2', 's3']],
              'scenes': [{'id': 'a', 'location': '站台', 'shotIds': ['s1']},
                         {'id': 'b', 'location': '车内', 'shotIds': ['s2', 's3']}]}
    record.project['script'] = script
    record.project['visualAssets'] = [
        {'id': 'v1', 'shotId': 's1', 'valid': True, 'objectKey': 'one.mp4'},
        {'id': 'v2', 'shotId': 's2', 'valid': True, 'cascadeFromShotId': 's1'},
        {'id': 'v3', 'shotId': 's3', 'valid': True, 'objectKey': 'unrelated.mp4'}]
    record.project['audioAssets'] = [{'shotId': sid, 'valid': True} for sid in ['s1', 's2', 's3']]
    record.project['lipSyncAssets'] = [{'shotId': sid, 'valid': True} for sid in ['s1', 's2', 's3']]
    record.project['timelines'] = {sid: {'visual': sid} for sid in ['s1', 's2', 's3']}
    record.project['exportManifest'] = {'objectKeys': {'video.mp4': 'old-export.mp4'}}
    await p._repository.save(record)
    draft = deepcopy(script)
    if change == 'shot':
        draft['shots'][0]['narration'] = '修改旁白'
    elif change == 'scene':
        draft['scenes'][0]['location'] = '路边车门'
    await p.update_script(pid, draft, expected_version=record.project['version'])
    saved = (await p._repository.get(pid)).project
    for group in ('visualAssets', 'audioAssets', 'lipSyncAssets'):
        assert [a['valid'] for a in saved[group]] == (
            [True, True, True] if change == 'none' else [False, False, True])
    assert saved['visualAssets'][0]['objectKey'] == 'one.mp4'
    if change != 'none':
        assert set(saved['timelines']) == {'s3'} and saved['exportManifest'] is None
        assert saved['visualAssets'][0]['invalidatedReason'] == 'input-changed'
        assert saved['visualAssets'][1]['invalidatedReason'] == 'dependency-changed'
    else:
        assert saved['exportManifest'] == record.project['exportManifest']
        assert saved['timelines'] == record.project['timelines']
