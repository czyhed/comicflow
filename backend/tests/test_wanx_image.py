import io
import json

import httpx
import pytest
from comicflow.providers.wanx_image import BailianImageProvider
from PIL import Image

_image_buffer = io.BytesIO()
Image.new('RGB', (2, 2), 'blue').save(_image_buffer, format='PNG')
_PNG = _image_buffer.getvalue()
_source_buffer = io.BytesIO()
Image.new('RGB', (256, 256), 'green').save(_source_buffer, format='PNG')
_SOURCE_PNG = _source_buffer.getvalue()


class _CapturingStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes, str]] = []

    async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
        self.writes.append((object_key, content, content_type))
        return object_key

    async def get_bytes(self, object_key: str, max_bytes: int = 20 * 1024 * 1024) -> bytes:
        assert object_key == 'characters/c1.png'
        assert len(_SOURCE_PNG) <= max_bytes
        return _SOURCE_PNG


def _handler(_request: httpx.Request, polled: list[int]) -> httpx.Response:
    path = _request.url.path
    if path.endswith("/image-synthesis"):
        return httpx.Response(200, json={"output": {"task_id": "task-1", "task_status": "PENDING"}})
    if path.endswith("/tasks/task-1"):
        polled[0] += 1
        if polled[0] < 2:
            return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
        succeeded = {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://img.test/k.png"}]}}
        return httpx.Response(200, json=succeeded)
    assert 'authorization' not in _request.headers
    return httpx.Response(200, content=_PNG)


@pytest.mark.asyncio
async def test_wanx_provider_submits_polls_downloads_and_persists() -> None:
    polled: list[int] = [0]
    store = _CapturingStore()
    provider = BailianImageProvider(
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        transport=httpx.MockTransport(lambda request: _handler(request, polled)),  # type: ignore[arg-type]
        asset_store=store,  # type: ignore[arg-type]
        poll_interval_seconds=0,
    )
    shot = {"id": "shot-1", "sceneId": "scene_1", "title": "回头", "durationSec": 6,
            "visualDescription": "姐姐在最后一排回头", "action": "回头", "emotion": "惊讶"}
    result = await provider.generate(shot, [{"id": "chr-1", "name": "姐姐"}])

    assert result["provider"] == "wanx"
    assert result["modelVersion"] == "wanx2.1-t2i-plus"
    assert result["mediaType"] == "image"
    assert result["requestReference"] == "task-1"
    assert result["shotId"] == "shot-1"
    assert result["characterRefs"] == ["chr-1"]
    assert polled[0] >= 2
    assert store.writes and store.writes[0][2] == "image/png"
    assert result["objectKey"] == store.writes[0][0]
    assert result["sizeBytes"] == len(store.writes[0][1])
    # PNG header survives round trip
    assert Image.open(io.BytesIO(store.writes[0][1])).format == "PNG"


@pytest.mark.asyncio
async def test_wanx_provider_reports_failed_task() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if _request.url.path.endswith("/image-synthesis"):
            pending = {"output": {"task_id": "task-f", "task_status": "PENDING"}}
            return httpx.Response(200, json=pending)
        failed = {"output": {"task_status": "FAILED", "message": "content rejected"}}
        return httpx.Response(200, json=failed)

    provider = BailianImageProvider(
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        poll_interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match="PROVIDER_GENERATION_FAILED"):
        await provider.generate({"id": "shot-1", "durationSec": 4}, [])


@pytest.mark.parametrize('model,protocol,submit,query', [
    ('wan2.6-image', 'auto', '', ''),
    ('my-image-deployment', 'wan26-image', '/custom/generate', '/custom/tasks/{task_id}'),
])
async def test_wan26_image_uses_configured_model_and_messages_protocol(
    model, protocol, submit, query,
):
    calls = []
    submit_url = '/api/v1' + (submit or '/services/aigc/image-generation/generation')
    query_url = '/api/v1' + (query or '/tasks/{task_id}').replace('{task_id}', 'task-26')

    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            assert request.url.path == submit_url
            assert request.headers['X-DashScope-Async'] == 'enable'
            body = json.loads(request.content)
            assert body['model'] == model
            assert body['input']['messages'][0]['content'][0]['text'].startswith('角色测试')
            assert body['parameters'] == {
                'size': '720*1280', 'n': 1, 'enable_interleave': True, 'max_images': 1,
            }
            return httpx.Response(200, json={'output': {'task_id': 'task-26'}})
        if request.url.host == 'dashscope.aliyuncs.com':
            assert request.url.path == query_url
            return httpx.Response(200, json={'output': {
                'task_status': 'SUCCEEDED', 'choices': [{'message': {'content': [
                    {'type': 'text', 'text': '说明'},
                    {'type': 'image', 'image': 'https://img.test/result.png'},
                ]}}],
            }})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=_PNG)

    provider = BailianImageProvider(
        api_key='offline', model=model, image_protocol=protocol,
        submit_path=submit, query_path=query, transport=httpx.MockTransport(handler),
        asset_store=_CapturingStore(), poll_interval_seconds=0,
    )
    result = await provider.generate({
        'id': 'c1', 'imagePurpose': 'character-reference', 'visualDescription': '角色测试',
    }, [])
    assert result['mediaType'] == 'image'
    assert result['modelVersion'] == model
    assert result['requestReference'] == 'task-26'
    assert result['objectKey'].endswith('.png')
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_wan26_image_edit_uses_approved_source_and_edit_parameters() -> None:
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            body = json.loads(request.content)
            content = body['input']['messages'][0]['content']
            assert content[0]['text'].startswith('基于已确认的角色参考图')
            assert content[1]['image'].startswith('data:image/png;base64,')
            assert body['parameters'] == {
                'size': '720*1280', 'n': 1, 'enable_interleave': False,
                'prompt_extend': True, 'watermark': False,
            }
            return httpx.Response(200, json={'output': {'task_id': 'task-edit'}})
        if request.url.path.endswith('/tasks/task-edit'):
            return httpx.Response(200, json={'output': {
                'task_status': 'SUCCEEDED', 'choices': [{'message': {'content': [
                    {'type': 'image', 'image': 'https://img.test/edit.png'},
                ]}}],
            }})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=_PNG)

    provider = BailianImageProvider(
        api_key='offline', model='wan2.6-image', image_protocol='auto',
        transport=httpx.MockTransport(handler), asset_store=_CapturingStore(),
        poll_interval_seconds=0,
    )
    result = await provider.generate({
        'id': 'view-1', 'imagePurpose': 'character-reference-view',
        'visualDescription': '基于已确认的角色参考图，生成正面视角。',
        'sourceImageObjectKey': 'characters/c1.png',
    }, [])

    assert result['mediaType'] == 'image'
    assert result['requestReference'] == 'task-edit'
    assert len(calls) == 3
