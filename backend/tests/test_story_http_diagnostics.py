"""Exercise the story API with upstream refusals, without external requests."""
import socket

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.doubao_text import DoubaoTextProvider
from comicflow.providers.text_errors import text_request_error


@pytest.mark.parametrize('content', [
    b'not JSON secret-key',
    b'{"error":{"code":[],"param":{"secret":"private"}}}',
    b'{"error":{"code":"secret-key","param":"private"}}',
    b' ' * 17000 + b'{"error":{"code":"InvalidParameter"}}',
])
async def test_unreadable_or_untrusted_error_body_is_not_exposed(content):
    error = await text_request_error(
        httpx.Response(400, content=content), 'PROVIDER_REQUEST_INVALID',
    )
    assert error.detail == {
        'stage': 'story_text', 'upstreamStatus': 400, 'reason': 'request_rejected',
    }


@pytest.mark.parametrize(('status', 'code', 'reason', 'api_status'), [
    (400, 'InvalidParameter', 'invalid_parameter', 400),
    (404, 'InvalidEndpointOrModel.NotFound', 'model_or_endpoint_not_found', 400),
    (403, 'ModelNotOpen', 'model_not_enabled', 401),
    (401, 'InvalidApiKey', 'authentication', 401),
    (429, 'anything', 'rate_limited', 429),
    (500, 'anything', 'service_error', 503),
    (400, 'secret-key', 'request_rejected', 400),
])
async def test_story_retains_safe_upstream_diagnostic(
    monkeypatch, status, code, reason, api_status,
):
    def deny_network(*args, **kwargs):
        raise AssertionError('Real network is forbidden')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {
            'code': code, 'param': 'model',
            'message': 'secret-key https://private.test/?signature=private',
        }})

    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(DoubaoTextProvider(
        api_key='secret-key', transport=httpx.MockTransport(handler),
    ))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://local',
    ) as client:
        created = await client.post('/api/projects', json={
            'inputType': 'story', 'story': 'A traveler waits for a letter on a rainy night.',
            'durationSec': 30, 'mode': 'automatic',
        })
        root = '/api/projects/' + created.json()['project']['id']
        response = await client.post(root + '/story')
        saved = (await client.get(root)).json()['project']

    assert response.status_code == api_status
    detail = {key: value for key, value in response.json().items() if key != 'error'}
    assert detail == {
        'stage': 'story_text', 'upstreamStatus': status,
        'reason': reason, 'parameter': 'model',
    }
    assert saved['generationErrorDetail'] == detail
    assert saved['stage'] == 'story-failed'
    assert len(calls) == 1
    assert 'secret-key' not in response.text
    assert 'private.test' not in response.text
