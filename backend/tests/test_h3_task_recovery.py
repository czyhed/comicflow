import copy
import importlib.util
import socket
from pathlib import Path

import httpx
import pytest
from comicflow.providers.minimax_h3 import MinimaxH3Provider

spec = importlib.util.spec_from_file_location(
    'recover_h3_task', Path(__file__).resolve().parents[2] / 'scripts/recover_h3_task.py',
)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('Recovery tests must not use a real socket')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)


def project():
    return {'id': 'p1', 'version': 3, 'script': {'shots': [{'id': 's1', 'durationSec': 5}]},
            'visualAssets': []}


async def test_retrieve_uses_existing_task_get_only_and_no_key_on_download():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == 'GET'
        if request.url.host == 'cp.compshare.cn':
            assert request.headers['authorization'] == 'Bearer offline'
            return httpx.Response(200, json={'task': {
                'id': 'known-task', 'status': 'succeeded', 'duration': 5, 'model': 'MiniMax-H3',
                'content': {'url': 'https://assets.test/video.mp4?secret=private'},
            }})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=b'offline-video-bytes')

    provider = MinimaxH3Provider(api_key='offline', poll_interval_seconds=0)
    task, video = await recovery.retrieve_existing(
        provider, 'known-task', 5, transport=httpx.MockTransport(handler),
    )
    assert task['id'] == 'known-task'
    assert video == b'offline-video-bytes'
    assert len(requests) == 2


@pytest.mark.parametrize('change', [{'id': 'other-task'}, {'duration': 8},
                                    {'model': 'other-model'}])
async def test_mismatched_task_is_not_downloaded(change):
    def handler(request):
        assert request.url.host == 'cp.compshare.cn'
        return httpx.Response(200, json={'task': {
            'id': 'known-task', 'status': 'succeeded', 'duration': 5, 'model': 'MiniMax-H3',
            'content': {'url': 'https://assets.test/video.mp4'}, **change,
        }})

    with pytest.raises(RuntimeError, match='H3_RECOVERY_TASK_MISMATCH'):
        await recovery.retrieve_existing(
            MinimaxH3Provider(api_key='offline'), 'known-task', 5,
            transport=httpx.MockTransport(handler),
        )


def test_recovery_is_idempotent_and_does_not_invent_prompt_metadata():
    before = project()
    asset = {'id': 'recovered', 'shotId': 's1', 'requestReference': 'task',
             'objectKey': 'videos/p1/s1/task.mp4', 'valid': True}
    result = recovery.attach_asset(before, copy.deepcopy(before), 's1', asset)
    assert before['visualAssets'] == []
    assert result['visualAssets'] == [asset]
    assert result['downstreamInvalidated'] is True
    assert recovery.find_existing(result, 's1', 'task') == asset
    assert 'promptExecution' not in asset


@pytest.mark.parametrize('mutation', ['version', 'script', 'existing-video'])
def test_concurrent_edits_and_existing_videos_are_not_overwritten(mutation):
    before = project()
    current = copy.deepcopy(before)
    if mutation == 'version':
        current['version'] = 4
    elif mutation == 'script':
        current['script']['shots'][0]['durationSec'] = 8
    else:
        current['visualAssets'].append({'shotId': 's1', 'valid': True})
    with pytest.raises(RuntimeError, match='H3_RECOVERY_PROJECT_CHANGED'):
        recovery.attach_asset(before, current, 's1', {'shotId': 's1'})


def test_invalidated_existing_task_is_not_restored_implicitly():
    current = project()
    current['visualAssets'].append({'shotId': 's1', 'requestReference': 'task', 'valid': False})
    with pytest.raises(RuntimeError, match='H3_RECOVERY_ASSET_INVALIDATED'):
        recovery.find_existing(current, 's1', 'task')
