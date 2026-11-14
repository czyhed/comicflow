"""Exercise prompt -> approval -> references via saved models without network."""

import base64
import io
import json
import socket

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from PIL import Image


async def test_registry_prompt_candidate_views_and_scene(monkeypatch):
    def deny_network(*args, **kwargs):
        pytest.fail('Real network forbidden in generation simulation')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny_network)
    objects = {}

    class Store:
        async def put_bytes(self, object_key, content, content_type):
            objects[object_key] = content

        async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
            assert len(objects[key]) <= max_bytes
            return objects[key]

        async def presigned_get_url(self, key, expires_in=900):
            return f'https://local-assets.test/{key}'

    png = io.BytesIO()
    Image.new('RGB', (720, 1280), 'gray').save(png, format='PNG')
    encoded = base64.b64encode(png.getvalue()).decode()
    fields = {'name': '小雨', 'appearance': '黑色短发', 'clothing': '蓝色工作服',
              'personality': '沉稳', 'referenceImagePrompt': '写实风格，蓝色棉布工作服，正面全身。'}
    calls = []
    image_prompts = []

    async def handler(_transport, request):
        calls.append((request.method, request.url.host, request.url.path))
        if request.url.host == 'text.test':
            body = json.loads(request.content)
            assert request.extensions['timeout']['read'] == 300
            assert body['model'] == 'chosen-text'
            assert 'ComicFlow task: character-prompt' in body['messages'][0]['content']
            context = json.loads(body['messages'][1]['content'])
            assert context['story'] == '完整故事：维修工小雨夜归。'
            return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({
                k: v for k, v in fields.items() if k != 'name'
            })}}]})
        if request.url.host == 'image.test':
            assert request.url.path == '/v1/chat/completions'
            body = json.loads(request.content)
            assert body['model'] == 'gpt-image-2.5'
            image_prompts.append(body['messages'][0]['content'])
            return httpx.Response(200, json={'choices': [{'message': {
                'content': f'![image](data:image/png;base64,{encoded})',
            }}]})
        if request.url.host == 'dashscope.aliyuncs.com':
            if request.method == 'POST':
                assert request.url.path == '/api/v1/services/aigc/image-generation/generation'
                body = json.loads(request.content)
                assert body['model'] == 'wan2.6-image'
                content = body['input']['messages'][0]['content']
                assert content[1]['image'] == f'data:image/png;base64,{encoded}'
                assert body['parameters']['enable_interleave'] is False
                assert body['parameters']['n'] == 1
                return httpx.Response(200, json={'output': {'task_id': 'offline-edit'}})
            assert request.url.path == '/api/v1/tasks/offline-edit'
            return httpx.Response(200, json={'output': {'task_status': 'SUCCEEDED',
                'choices': [{'message': {'content': [{'image': 'https://result.test/view.png'}]}}],
            }})
        assert request.url.host == 'result.test'
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=png.getvalue())

    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', handler)
    runtime = create_memory_runtime()
    runtime.pipeline._asset_store = Store()
    registry = runtime.model_registry
    bindings = {}
    for usage, protocol, base, model, config in [
        ('character-prompt', 'doubao-chat', 'https://text.test/api/v3', 'chosen-text', {
            'timeoutMs': 300000, 'request': {'path': '/chat/completions',
                'body': {'model': '{{model}}', 'messages': '{{messages}}'}},
        }),
        ('image', 'chat-image', 'https://image.test', 'gpt-image-2.5', {}),
        ('image-edit', 'wan26-image', 'https://dashscope.aliyuncs.com/api/v1',
         'wan2.6-image', {}),
    ]:
        view = await registry.mutate('connection', None, {
            'revision': (await registry.view())['revision'], 'name': usage,
            'baseUrl': base, 'apiKey': 'offline-key',
        })
        view = await registry.mutate('model', None, {
            'revision': view['revision'], 'name': model,
            'connectionId': view['connections'][-1]['id'], 'protocol': protocol,
            'model': model, 'enabled': True, 'config': config,
        })
        bindings[usage] = view['models'][-1]['id']
    await registry.bind({'revision': view['revision'], 'bindings': bindings})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        created_response = await client.post('/api/projects', json={
            'inputType': 'story', 'story': '雨夜，维修工小雨下班后独自走向车站。',
            'durationSec': 30, 'mode': 'import_story',
        })
        assert created_response.status_code == 201, created_response.text
        created = created_response.json()
        pid = created['project']['id']
        root = f'/api/projects/{pid}'
        card_response = await client.post(root + '/characters', json={
            **fields, 'voice': {'language': 'zh-CN'},
        })
        assert card_response.status_code == 201, card_response.text
        card = card_response.json()
        cid = card['id']
        record = await runtime.pipeline._repository.get(pid)
        record.project['generatedStoryText'] = '完整故事：维修工小雨夜归。'
        record.project['script'] = {
            'title': '夜归', 'scenes': [{'id': 'sc1', 'location': '车站', 'time': '夜晚',
                                    'shotIds': ['s1']}],
            'shots': [{'id': 's1', 'characterIds': [cid], 'visualDescription': '小雨走进车站'}],
        }
        await runtime.pipeline._repository.save(record)
        preview = await client.post(root + '/characters/prompt-preview', json={
            'expectedVersion': record.project['version'], 'characterId': cid,
            'expectedRevision': card.get('revision', 0), 'fields': fields, 'instructions': '',
        })
        assert preview.status_code == 200, preview.text
        saved = await client.patch(root + f'/characters/{cid}', json={
            **preview.json()['draft'], 'voice': {'language': 'zh-CN'},
            'expectedRevision': card.get('revision', 0),
        })
        assert saved.status_code == 200, saved.text

        async def post(path, **payload):
            version = (await client.get(root)).json()['project']['version']
            response = await client.post(root + path, json={'expectedVersion': version, **payload})
            assert response.status_code == 200, response.text
            return response.json()

        candidate = await post(f'/characters/{cid}/reference-candidate')
        assert candidate['candidate']['skillExecution']['skill'] == 'xiaoluo-visual-assets'
        assert fields['referenceImagePrompt'] in image_prompts[0]
        approved = await post(f'/characters/{cid}/reference-candidate/approve',
                              candidateId=candidate['candidate']['id'])
        assert approved['character']['referenceImageStatus'] == 'approved'
        views = await post(f'/characters/{cid}/reference-views')
        assert len(views['views']) == 3
        board = views['character']['referenceBoard']
        assert objects[board['objectKey']]
        from comicflow.providers.h3_inputs import image_data
        assert image_data(objects[board['objectKey']]).startswith('data:image/png;base64,')
        assert all(v['skillExecution']['skill'] == 'xiaoluo-visual-assets' for v in views['views'])
        before = len(calls)
        assert (await post(f'/characters/{cid}/reference-views'))['reused']
        assert len(calls) == before
        # Older saved strips are rebuilt locally from saved images, without
        # another image-generation request or deleting approved references.
        old_card = await runtime.pipeline._character_repository.get(cid)
        old_card['referenceBoard'].pop('columns')
        await runtime.pipeline._character_repository.save(old_card)
        rebuilt = await post(f'/characters/{cid}/reference-views')
        assert rebuilt['reused']
        assert rebuilt['character']['referenceBoard']['columns'] == 2
        assert len(calls) == before
        await post('/references/scenes/sc1')
        project = (await client.get(root)).json()['project']
        scene = project['script']['scenes'][0]
        assert objects[scene['backgroundImageObjectKey']]
        assert scene['backgroundImageSkillExecution']['skill'] == 'xiaoluo-visual-assets'
        assert len(image_prompts) == 2
        assert len([c for c in calls if c[0] == 'POST' and c[1] == 'text.test']) == 1
        assert len([c for c in calls if c[0] == 'POST' and c[1] == 'dashscope.aliyuncs.com']) == 3
