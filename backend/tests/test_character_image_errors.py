import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.wanx_image import BailianImageProvider


async def reference_response(provider):
    runtime = create_memory_runtime()
    runtime.pipeline.set_reference_image_provider(provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        created = (await client.post('/api/projects', json={
            'inputType': 'story', 'story': '雨夜，小雨在车站等车，遇到故人。', 'durationSec': 30,
            'mode': 'import_story',
        })).json()
        root = '/api/projects/' + created['project']['id']
        card = (await client.post(root + '/characters', json={
            'name': '小雨', 'appearance': '黑色短发', 'clothing': '蓝色外套',
            'personality': '沉稳', 'voice': {'language': 'zh-CN'},
        })).json()
        version = (await client.get(root)).json()['project']['version']
        result = await client.post(root + '/references/characters/' + card['id'], json={
            'expectedVersion': version,
        })
        saved = await runtime.pipeline._character_repository.get(card['id'])
        assert not saved.get('referenceImageUrl')
        assert (await client.get(root)).json()['project']['version'] == version
        return result


async def test_incompatible_image_model_is_rejected_before_submission():
    calls = []

    def handler(request):
        calls.append(request)
        # Simulate a V2 endpoint rejecting the unrelated image-editing model.
        return httpx.Response(400, json={'code': 'InvalidParameter', 'message': 'model invalid'})

    response = await reference_response(BailianImageProvider(
        api_key='offline', model='wan2.6-image', image_protocol='wan-v2',
        transport=httpx.MockTransport(handler),
    ))
    assert response.status_code == 400, response.text
    assert response.json()['error'] == 'IMAGE_MODEL_UNSUPPORTED'
    assert calls == []


@pytest.mark.parametrize('status,code,expected_status,expected_code', [
    (401, 'InvalidApiKey', 401, 'PROVIDER_AUTH_FAILED'),
    (400, 'InvalidParameter', 400, 'IMAGE_REQUEST_INVALID'),
    (429, 'Throttling', 429, 'IMAGE_RATE_LIMITED'),
    (403, 'AllocationQuota.FreeTierOnly', 409, 'IMAGE_QUOTA_EXHAUSTED'),
    (500, 'InternalError', 503, 'PROVIDER_UNAVAILABLE'),
])
async def test_character_image_upstream_error_classification(
    status, code, expected_status, expected_code,
):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'code': code, 'message': 'SECRET upstream content'})

    response = await reference_response(BailianImageProvider(
        api_key='offline', transport=httpx.MockTransport(handler),
    ))
    assert response.status_code == expected_status, response.text
    assert response.json()['error'] == expected_code
    assert 'SECRET' not in response.text
    assert len(calls) == 1


async def test_image_protocol_configuration_is_atomic_and_keeps_selected_model():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        root = '/api/provider-config/profiles/image/production'
        payload = {
            'provider': 'bailian-image', 'model': 'wan2.6-image',
            'baseUrl': 'https://images.test/api/v1', 'enabled': True,
            'apiKey': 'offline-key', 'timeoutMs': 180000, 'imageProtocol': 'wan26-image',
            'requestPath': '/custom/images', 'statusPath': '/jobs/{task_id}',
        }
        result = await client.put(root, json=payload)
        assert result.status_code == 200, result.text
        assert result.json()['model'] == 'wan2.6-image'
        assert result.json()['imageProtocol'] == 'wan26-image'
        payload['imageProtocol'] = 'wan-v2'
        assert (await client.put(root, json=payload)).status_code == 400
        config = (await client.get('/api/provider-config')).json()
        assert config['image']['imageProtocol'] == 'wan26-image'
        assert 'offline-key' not in str(config)
        payload['imageProtocol'] = 'wan26-image'
        payload['requestPath'] = 'https://other.test/leak'
        assert (await client.put(root, json=payload)).status_code == 400
