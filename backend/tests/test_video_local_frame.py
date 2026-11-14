import io
import json

import httpx
import pytest
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
from PIL import Image


@pytest.mark.parametrize('model', ['wan2.7-i2v', 'wan2.7-i2v-2026-04-25', 'wan2.6-i2v'])
async def test_stored_frame_sent_as_image_data_without_local_url_or_extra_submission(model):
    buffer = io.BytesIO()
    Image.new('RGB', (256, 256), 'blue').save(buffer, format='PNG')
    calls = []

    class Store:
        async def get_bytes(self, object_key, max_bytes):
            assert object_key == 'backgrounds/scene.png'
            return buffer.getvalue()

        async def put_bytes(self, object_key, content, content_type):
            pass

    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            body = json.loads(request.content)
            if model.startswith('wan2.7'):
                assert 'img_url' not in body['input']
                assert len(body['input']['media']) == 1
                assert body['input']['media'][0]['type'] == 'first_frame'
                frame = body['input']['media'][0]['url']
            else:
                assert 'media' not in body['input']
                frame = body['input']['img_url']
            assert frame.startswith('data:image/png;base64,')
            assert '127.0.0.1' not in request.content.decode()
            return httpx.Response(200, json={'output': {'task_id': 'v1'}})
        if '/tasks/' in request.url.path:
            return httpx.Response(200, json={'output': {
                'task_status': 'SUCCEEDED', 'video_url': 'https://assets.test/v.mp4',
            }})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=b'video')

    provider = BailianImageToVideoProvider(
        api_key='offline', model=model, resolution='720P',
        asset_store=Store(), transport=httpx.MockTransport(handler),
    )
    await provider.generate({
        'id': 's1', 'durationSec': 5, 'visualDescription': '雨夜车站',
        'firstFrameUrl': 'http://127.0.0.1:19000/bucket/scene.png',
        'firstFrameObjectKey': 'backgrounds/scene.png',
    }, [])
    assert len(calls) == 3


@pytest.mark.parametrize('url', ['http://127.0.0.1/f.png', 'http://localhost/f.png',
                               'http://192.168.1.2/f.png'])
async def test_local_frame_without_stored_object_never_submits(url):
    def handler(request):
        pytest.fail('Local-only image must not reach supplier')

    provider = BailianImageToVideoProvider(
        api_key='offline', transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match='VIDEO_FIRST_FRAME_UNREACHABLE'):
        await provider.generate({'id': 's1', 'durationSec': 5, 'visualDescription': '雨夜',
                                 'firstFrameUrl': url}, [])


@pytest.mark.parametrize('source', ['scene', 'character', 'shot'])
async def test_pipeline_passes_stored_first_frame_key(source):
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    pipeline = create_memory_runtime().pipeline
    class Store:
        async def presigned_get_url(self, key, expires_in=900):
            return 'http://127.0.0.1:19000/bucket/frame.png'

    pipeline._asset_store = Store()
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，小雨在车站等候她的姐姐，远处传来汽笛声。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await pipeline._repository.get(pid)
    await pipeline._character_repository.save({
        'id': 'c1', 'name': '小雨', 'appearance': '短发', 'clothing': '外套',
        'personality': '沉稳', 'voice': {}, 'referenceImageObjectKey': 'char.png',
    })
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1'], 'backgroundImageObjectKey': 'scene.png'}],
        'shots': [{'id': 's1', 'order': 1, 'durationSec': 5, 'visualDescription': '雨夜车站',
                   'characterIds': ['c1'] if source == 'character' else []}],
    }
    if source == 'shot':
        record.project['visualAssets'] = [{'id': 'a1', 'shotId': 's1', 'valid': True,
                                          'mediaType': 'image', 'objectKey': 'shot.png'}]
    await pipeline._repository.save(record)

    class CapturingProvider(BailianImageToVideoProvider):
        async def generate(self, shot, characters, **kwargs):
            assert shot['firstFrameObjectKey'] == {
                'scene': 'scene.png', 'character': 'char.png', 'shot': 'shot.png',
            }[source]
            raise RuntimeError('VIDEO_FIRST_FRAME_UNREADABLE')

    from comicflow.domain.errors import DomainError
    pipeline.set_video_provider(CapturingProvider(api_key='offline'))
    with pytest.raises(DomainError, match='VIDEO_FIRST_FRAME_UNREADABLE'):
        await pipeline.generate_shot_visual(pid, 's1', expected_version=record.project['version'])


@pytest.mark.parametrize('content', [b'not-an-image', b''])
async def test_invalid_stored_frame_never_submits(content):
    class Store:
        async def get_bytes(self, object_key, max_bytes):
            return content

    def handler(request):
        pytest.fail('Invalid stored image must not trigger paid submission')

    provider = BailianImageToVideoProvider(
        api_key='offline', asset_store=Store(), transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match='REFERENCE_IMAGE_INVALID'):
        await provider.generate({'id': 's1', 'firstFrameObjectKey': 'frame.png',
                                 'durationSec': 5, 'visualDescription': '车站'}, [])
