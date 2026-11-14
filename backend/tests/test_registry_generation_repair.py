import base64
import io

import httpx
import pytest
from comicflow.domain.errors import DomainError
from comicflow.providers.model_protocols import validate_config
from comicflow.providers.model_selection import ModelSelection
from PIL import Image


def selection(protocol, base_url, config=None):
    return ModelSelection({
        'bindings': {'image': 'm'},
        'connections': [{'id': 'c', 'baseUrl': base_url, 'apiKey': 'offline'}],
        'models': [{'id': 'm', 'connectionId': 'c', 'enabled': True,
                    'model': 'wan2.6-image' if protocol == 'wan26-image' else 'gpt-image-2.5',
                    'protocol': protocol, 'config': validate_config(protocol, config or {})}],
    }, None)


@pytest.mark.parametrize('custom_path', [None, '/custom/image', 'body-only'])
async def test_registry_chat_image_default_keeps_adapter_endpoint(custom_path):
    config = {'request': {'path': custom_path}} if custom_path else {}
    if custom_path == 'body-only':
        config = {'request': {'body': {'model': '{{model}}', 'messages': '{{messages}}'}}}
    provider = selection('chat-image', 'https://image.test', config).provider('image', None)
    png = io.BytesIO()
    Image.new('RGB', (16, 16)).save(png, format='PNG')
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == (
            custom_path if custom_path and custom_path != 'body-only' else '/v1/chat/completions'
        )
        return httpx.Response(200, json={'choices': [{'message': {
            'content': '![image](data:image/png;base64,' +
            base64.b64encode(png.getvalue()).decode() + ')',
        }}]})

    provider._transport.inner = httpx.MockTransport(handler)
    result = await provider.generate({'id': 'scene', 'imagePurpose': 'scene-background',
                                      'visualDescription': '空旷的雨夜车站'}, [])
    assert result['mediaType'] == 'image'
    assert len(calls) == 1


def test_native_wan_image_rejects_dashscope_text_endpoint_before_network():
    with pytest.raises(DomainError, match='MODEL_ENDPOINT_MISMATCH'):
        selection('wan26-image', 'https://dashscope.aliyuncs.com/compatible-mode/v1').provider(
            'image', None,
        )


def test_native_wan_image_allows_native_endpoint_and_explicit_private_gateway():
    for base in ['https://dashscope.aliyuncs.com/api/v1', 'https://private.test/custom']:
        assert selection('wan26-image', base).provider('image', None) is not None


async def test_registry_rejects_native_endpoint_mismatch_atomically():
    from comicflow.providers.model_registry import (
        MemoryRegistryRepository,
        ModelRegistry,
        SecretCipher,
    )

    registry = ModelRegistry(MemoryRegistryRepository(), SecretCipher.ephemeral())
    view = await registry.mutate('connection', None, {
        'revision': 0, 'name': 'images',
        'baseUrl': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'apiKey': 'offline',
    })
    connection = view['connections'][0]
    payload = {'revision': view['revision'], 'connectionId': connection['id'], 'name': 'edit',
               'protocol': 'wan26-image', 'model': 'wan2.6-image', 'enabled': True, 'config': {}}
    with pytest.raises(DomainError, match='MODEL_ENDPOINT_MISMATCH'):
        await registry.mutate('model', None, payload)
    assert await registry.view() == view
    corrected = await registry.mutate('connection', connection['id'], {
        'revision': view['revision'], 'name': 'native images',
        'baseUrl': 'https://dashscope.aliyuncs.com/api/v1',
    })
    assert corrected['connections'][0]['configured']
    payload['revision'] = corrected['revision']
    corrected = await registry.mutate('model', None, payload)
    with pytest.raises(DomainError, match='MODEL_ENDPOINT_MISMATCH'):
        await registry.mutate('connection', connection['id'], {
            'revision': corrected['revision'], 'name': 'wrong text endpoint',
            'baseUrl': connection['baseUrl'],
        })
    assert await registry.view() == corrected
