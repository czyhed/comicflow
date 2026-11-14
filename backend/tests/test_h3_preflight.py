import io
import json

import httpx
import pytest
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from PIL import Image
from test_h3_skill_execution import valid_rewrite


def png(size=(256, 256)):
    buffer = io.BytesIO()
    Image.new('RGB', size, 'navy').save(buffer, format='PNG')
    return buffer.getvalue()


@pytest.mark.parametrize('source', ['first', 'last', 'character', 'scene'])
async def test_h3_local_images_prepared_before_text_and_not_sent_to_text(source):
    events = []
    shot = {'id': 's1', 'durationSec': 5}
    characters = []
    url = 'http://127.0.0.1:19000/bucket/frame.png?Signature=private-signature'
    if source in {'first', 'last'}:
        shot[f'{source}FrameUrl'] = url
        shot[f'{source}FrameObjectKey'] = 'frame.png'
    elif source == 'character':
        characters = [{'id': 'c1', 'referenceImageUrl': url,
                       'referenceImageObjectKey': 'frame.png'}]
    else:
        shot['referenceImages'] = [{'id': 'scene1', 'url': url, 'objectKey': 'frame.png'}]

    class Store:
        async def get_bytes(self, key, max_bytes):
            events.append('read')
            return png()

        async def put_bytes(self, **kwargs):
            events.append('store')

    async def complete(system, user):
        events.append('text')
        assert 'base64' not in user
        assert 'private-signature' not in user
        assert '127.0.0.1' not in user
        return await valid_rewrite(system, user)

    def handler(request):
        if request.method == 'POST':
            events.append('submit')
            content = json.loads(request.content)['content']
            assert content[1]['image_url']['url'].startswith('data:image/png;base64,')
            return httpx.Response(200, json={'task_id': 't1'})
        if '/query/' in request.url.path:
            return httpx.Response(200, json={'task': {
                'status': 'succeeded', 'content': {'url': 'https://assets.test/v.mp4'},
            }})
        return httpx.Response(200, content=b'mocked-video')

    provider = MinimaxH3Provider(api_key='offline', asset_store=Store(),
        prompt_writer=H3SkillPromptWriter(complete), transport=httpx.MockTransport(handler))
    asset = await provider.generate(shot, characters)
    assert events == ['read', 'text', 'submit', 'store']
    assert 'base64' not in json.dumps(asset)


@pytest.mark.parametrize('problem,expected', [
    ('no-key', 'H3_REFERENCE_UNREACHABLE'),
    ('read', 'H3_REFERENCE_UNREADABLE'),
    ('invalid-image', 'REFERENCE_IMAGE_INVALID'),
    ('dimensions', 'REFERENCE_IMAGE_INVALID'),
])
async def test_preflight_failure_never_calls_text_or_video(problem, expected):
    class Store:
        async def get_bytes(self, key, max_bytes):
            if problem == 'read':
                raise OSError('private storage details')
            return b'bad-image' if problem == 'invalid-image' else png((128, 256))

    async def complete(system, user):
        pytest.fail('Preflight failure must not spend text quota')

    def handler(request):
        pytest.fail('Preflight failure must not spend video quota')

    provider = MinimaxH3Provider(api_key='offline', asset_store=Store(),
        prompt_writer=H3SkillPromptWriter(complete), transport=httpx.MockTransport(handler))
    shot = {'id': 's1', 'durationSec': 5, 'firstFrameUrl': 'http://127.0.0.1/frame.png'}
    if problem != 'no-key':
        shot['firstFrameObjectKey'] = 'frame.png'
    with pytest.raises(RuntimeError, match=f'^{expected}$'):
        await provider.generate(shot, [])
