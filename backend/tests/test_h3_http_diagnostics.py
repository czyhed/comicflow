"""Offline regression for errors formerly collapsed to a generic 503."""

import socket

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from test_h3_skill_execution import valid_rewrite


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('HTTP diagnosis must not use a real socket')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)


@pytest.mark.parametrize('phase', ['h3_submit', 'h3_poll', 'h3_result'])
@pytest.mark.parametrize('failure,reason,api_status,code', [
    (400, 'request_rejected', 400, 'VIDEO_REQUEST_INVALID'),
    (401, 'authentication', 401, 'PROVIDER_AUTH_FAILED'),
    (403, 'permission_denied', 401, 'PROVIDER_AUTH_FAILED'),
    (404, 'endpoint_not_found', 400, 'VIDEO_REQUEST_INVALID'),
    (402, 'quota_exhausted', 409, 'VIDEO_QUOTA_EXHAUSTED'),
    (429, 'rate_limited', 429, 'VIDEO_RATE_LIMITED'),
    (503, 'service_error', 503, 'PROVIDER_UNAVAILABLE'),
    ('timeout', 'timeout', 504, 'PROVIDER_TIMEOUT'),
    ('network', 'connection_error', 503, 'PROVIDER_UNAVAILABLE'),
])
async def test_h3_failure_reaches_api_with_stage_and_existing_task(
    phase, failure, reason, api_status, code, caplog,
):
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，一个人走进店内。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{'id': 's1', 'durationSec': 5}]}
    await runtime.pipeline._repository.save(record)
    calls = []

    def handler(request):
        calls.append(request.method)
        current = ('h3_submit' if request.method == 'POST' else
                   'h3_poll' if '/query/' in request.url.path else 'h3_result')
        if current == phase:
            if failure == 'timeout':
                raise httpx.ReadTimeout('private-secret', request=request)
            if failure == 'network':
                raise httpx.ConnectError('private-secret', request=request)
            return httpx.Response(failure, json={'error': {
                'code': 'private-secret', 'message': 'https://private.test/?key=private-secret',
            }})
        if current == 'h3_submit':
            return httpx.Response(200, json={'task_id': 'known-task-1'})
        return httpx.Response(200, json={'task': {
            'status': 'succeeded', 'content': {'url': 'https://assets.test/out.mp4'},
        }})

    provider = MinimaxH3Provider(
        api_key='private-secret', transport=httpx.MockTransport(handler),
        poll_interval_seconds=0,
    )
    runtime.pipeline.set_video_provider(provider)
    provider.set_prompt_writer(H3SkillPromptWriter(valid_rewrite))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })
    expected = {'error': code, 'stage': phase, 'reason': reason}
    if isinstance(failure, int):
        expected['upstreamStatus'] = failure
    if phase != 'h3_submit':
        expected['taskId'] = 'known-task-1'
    assert response.status_code == api_status
    assert response.json() == expected
    assert calls == (['POST'] if phase == 'h3_submit' else
                     ['POST', 'GET'] if phase == 'h3_poll' else ['POST', 'GET', 'GET'])
    assert not (await runtime.pipeline._repository.get(pid)).project.get('visualAssets')
    assert 'private-secret' not in response.text + caplog.text
    assert f'stage={phase}' in caplog.text
