from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.minimax_h3 import MinimaxH3Provider


@pytest.mark.parametrize('status', ['cancelled', 'canceled', 'failed', 'failure'])
async def test_terminal_task_details_reach_api_without_retry_or_asset_changes(status, caplog):
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，一名维修工走进公交车站。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [
        {'id': 's1', 'durationSec': 5, 'visualDescription': '雨夜，一名维修工走进车站。'},
    ]}
    await runtime.pipeline._repository.save(record)
    before = deepcopy(record.project)
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'existing-task'})
        return httpx.Response(200, json={'task': {'status': status,
            'error': {'message': 'private-text-and-key', 'code': 'private-code'}}})

    runtime.pipeline.set_video_provider(MinimaxH3Provider(
        api_key='private-key', transport=httpx.MockTransport(handler),
        prompt_mode='context-ir', poll_interval_seconds=0,
    ))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })
    cancelled = status in {'cancelled', 'canceled'}
    assert response.status_code == (409 if cancelled else 502), response.text
    assert response.json() == {
        'error': 'VIDEO_TASK_CANCELLED' if cancelled else 'VIDEO_GENERATION_FAILED',
        'stage': 'h3_poll', 'reason': 'task_cancelled' if cancelled else 'task_failed',
        'taskId': 'existing-task', 'taskStatus': 'cancelled' if cancelled else 'failed',
    }
    assert calls == ['POST', 'GET']
    assert (await runtime.pipeline._repository.get(pid)).project == before
    assert 'private' not in response.text + caplog.text
    assert 'task_id=existing-task' in caplog.text


async def test_moderating_is_pending_then_success_without_warning(caplog):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'existing-task'})
        if len(calls) == 2:
            return httpx.Response(200, json={'task': {'status': 'moderating'}})
        if len(calls) == 3:
            return httpx.Response(200, json={'task': {'status': 'succeeded',
                'content': {'url': 'https://assets.test/clip.mp4'}}})
        return httpx.Response(200, content=b'offline-video')

    provider = MinimaxH3Provider(api_key='offline', transport=httpx.MockTransport(handler),
                                prompt_mode='context-ir', poll_interval_seconds=0)
    result = await provider.generate({
        'id': 's1', 'durationSec': 5, 'visualDescription': '雨夜车站。',
    }, [])
    assert result['requestReference'] == 'existing-task'
    assert calls == ['POST', 'GET', 'GET', 'GET']
    assert 'unrecognised status' not in caplog.text
