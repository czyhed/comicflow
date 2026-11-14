"""Full HTTP/provider/FFmpeg flow with an explicit ban on real network connections."""

import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from PIL import Image


@pytest.mark.parametrize('input_kind', ['sample', 'current-project'])
@pytest.mark.parametrize('prompt_mode', ['local-skill', 'context-ir'])
async def test_h3_flow_with_real_ffmpeg_and_no_model_network(
    input_kind, prompt_mode, monkeypatch, tmp_path,
):
    if not shutil.which('ffmpeg'):
        pytest.skip('Install ffmpeg to run the complete offline media flow')
    if input_kind == 'current-project':
        fixture_path = os.getenv('COMICFLOW_OFFLINE_FIXTURE')
        if not fixture_path:
            pytest.skip('Set COMICFLOW_OFFLINE_FIXTURE to a local sanitized project copy')
        fixture = json.loads(await asyncio.to_thread(
            Path(fixture_path).read_text, encoding='utf-8',
        ))
    else:
        fixture = {
            'script': {
                'scenes': [{'id': 'scene1', 'shotIds': ['s1', 's2'],
                            'backgroundImageObjectKey': 'background.png'}],
                'shots': [{'id': shot_id, 'order': index, 'durationSec': 5,
                           'visualDescription': '学生走向走廊中的售货机。',
                           'narration': '学生饿得前胸贴后背。', 'dialogue': '等一下！\n我来了。',
                           'characterIds': ['c1']}
                          for index, shot_id in enumerate(['s1', 's2'], 1)],
            },
            'characters': [{'id': 'c1', 'name': '学生', 'appearance': '短发',
                            'clothing': '格子衬衫', 'personality': '活泼',
                            'referenceImageObjectKey': 'character.png'}],
        }

    def deny_network(*args, **kwargs):
        pytest.fail('Offline verification attempted a real socket connection')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny_network)
    runtime = create_memory_runtime()
    objects = {}
    png = io.BytesIO()
    Image.new('RGB', (720, 1280), 'navy').save(png, format='PNG')

    class Store:
        async def exists(self, key):
            return key in objects

        async def presigned_get_url(self, key, expires_in=900):
            return f'http://127.0.0.1:19000/offline/{key}?Signature=offline-signed'

        async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
            data = objects[key]
            assert len(data) <= max_bytes
            return data

        async def put_bytes(self, object_key, content, content_type):
            objects[object_key] = content

    store = Store()
    runtime.pipeline._asset_store = store
    for card in fixture['characters']:
        objects[card['referenceImageObjectKey']] = png.getvalue()
        await runtime.pipeline._character_repository.save({**card, 'voice': card.get('voice', {})})
    for scene in fixture['script']['scenes']:
        if scene.get('backgroundImageObjectKey'):
            objects[scene['backgroundImageObjectKey']] = png.getvalue()

    events = []
    videos = {}
    submitted_prompts = []
    for duration in {shot['durationSec'] for shot in fixture['script']['shots']}:
        path = tmp_path / f'offline-test-{duration}s.mp4'
        # Deterministic test media, never a real model result. No external input.
        await asyncio.to_thread(subprocess.run, [
            'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'testsrc2=size=256x256:rate=12', '-t', str(duration),
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(path),
        ], check=True, capture_output=True)
        videos[duration] = path.read_bytes()
    tasks = {}

    def handler(request):
        if request.url.host == 'text.test':
            assert prompt_mode == 'local-skill', 'Chinese route must not call a text model'
            events.append('text')
            body = json.loads(request.content)
            assert '# H3 Prompt Writing' in body['messages'][0]['content']
            context = json.loads(body['messages'][1]['content'])
            assert 'base64' not in json.dumps(context)
            assert 'Signature=' not in json.dumps(context)
            plan = context['referenceManifest']
            labels = ' '.join(image['label'] for image in plan['images'])
            dialogue = ' '.join(
                f'<d>[Chinese] {line}</d>'
                for field in ('dialogue', 'narration')
                for line in context['shot'].get(field, '').splitlines() if line
            )
            description = f'[Shot 1] A student runs through a hallway. {labels} {dialogue}'
            sections = {'integrated_multimodal_description': description,
                        'overall_soundscape': 'Footsteps.', 'non_diegetic_music': 'N/A'}
            if plan['mode'] == 'ref2va':
                sections = {
                    'subject_definitions': f'<Subject 1> is the student in {labels}.',
                    'summary': '<Subject 1> runs.', 'retention_analysis': 'Preserve appearance.',
                    'detailed_description': description, 'overall_soundscape': 'Footsteps.',
                    'non_diegetic_music': 'N/A',
                }
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {
                'content': json.dumps({'durationSec': plan['durationSec'], 'sections': sections}),
            }}]})
        if request.url.host == 'video.test':
            if request.method == 'POST':
                events.append('submit')
                body = json.loads(request.content)
                assert body['model'] == 'MiniMax-H3'
                assert body.get('use_context_ir', False) == (prompt_mode == 'context-ir')
                assert body['resolution'] == '768P'
                submitted_prompts.append(body['content'][0]['text'])
                for item in body['content'][1:]:
                    assert item['image_url']['url'].startswith('data:image/png;base64,')
                task_id = f'offline-task-{len(tasks) + 1}'
                tasks[task_id] = body['duration']
                return httpx.Response(200, json={'task_id': task_id})
            events.append('poll')
            task_id = request.url.path.split('/')[-1]
            assert task_id in tasks
            return httpx.Response(200, json={'task': {'status': 'succeeded',
                'content': {'url': f'https://assets.test/{task_id}'}}})
        assert request.url.host == 'assets.test'
        assert 'authorization' not in request.headers
        events.append('download')
        return httpx.Response(200, content=videos[tasks[request.url.path.strip('/')]])

    transport = httpx.MockTransport(handler)
    runtime.pipeline.set_text_provider(BailianTextProvider(
        api_key='offline-text-key', base_url='https://text.test/v1',
        model='qwen-plus', transport=transport,
    ))
    runtime.pipeline.set_video_provider(MinimaxH3Provider(
        api_key='offline-video-key', base_url='https://video.test',
        asset_store=store, transport=transport, poll_interval_seconds=0,
        prompt_mode=prompt_mode,
    ))
    # Exercise the same persisted-model routing used by the browser. Intercept
    # only HTTP transport; keep selection, adapters and media processing real.
    async def offline_http(_transport, request):
        return handler(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', offline_http)
    registry = runtime.model_registry
    bindings = {}
    for protocol, base_url, model, config, usages in [
        ('chat-completions', 'https://text.test/v1', 'qwen-plus', {
            'request': {'path': '/chat/completions', 'body': {
                'model': '{{model}}', 'messages': '{{messages}}',
            }},
        }, ['video-prompt']),
        ('compshare-h3', 'https://video.test', 'MiniMax-H3', {
            'h3PromptMode': prompt_mode, 'resolution': '768P',
        }, ['video']),
    ]:
        view = await registry.mutate('connection', None, {
            'revision': (await registry.view())['revision'], 'name': protocol,
            'baseUrl': base_url, 'apiKey': 'offline-key',
        })
        view = await registry.mutate('model', None, {
            'revision': view['revision'], 'name': model,
            'connectionId': view['connections'][-1]['id'], 'protocol': protocol,
            'model': model, 'enabled': True, 'config': config,
        })
        bindings.update(dict.fromkeys(usages, view['models'][-1]['id']))
    await registry.bind({'revision': view['revision'], 'bindings': bindings})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        created = (await client.post('/api/projects', json={
            'inputType': 'story', 'story': '学生跑向走廊里的自动售货机。',
            'mode': 'import_story', 'durationSec': 30,
        })).json()
        pid = created['project']['id']
        record = await runtime.pipeline._repository.get(pid)
        record.project['script'] = deepcopy(fixture['script'])
        await runtime.pipeline._repository.save(record)
        for shot in fixture['script']['shots']:
            response = await client.post(f'/api/projects/{pid}/shots/{shot["id"]}/visual', json={
                'expectedVersion': record.project['version'],
            })
            assert response.status_code == 200, response.text
            assert response.json()["awaitingAdoption"] is True
            adopted = await client.post(
                f"/api/projects/{pid}/video-jobs/{response.json()['jobId']}/adopt",
            )
            assert adopted.status_code == 200, adopted.text
            assert response.status_code == 200, response.text
            asset = response.json()['asset']
            assert asset['durationSec'] == shot['durationSec']
            if prompt_mode == 'local-skill':
                assert asset['promptExecution']['skill'] == 'h3-prompt-writing'
            else:
                assert asset['promptExecution']['mode'] == 'context-ir'
                assert asset['promptExecution']['localTextCall'] is False
            assert 'base64' not in json.dumps(asset)
            assert 'frameExtractionError' not in asset
            # The model wrote no spoken text at all; every project line must still
            # reach the vendor call verbatim.
            prompt = submitted_prompts[-1]
            for field in ('dialogue', 'narration'):
                for line in shot.get(field, '').splitlines():
                    if line.strip():
                        if prompt_mode == 'local-skill':
                            assert f'<d>[Chinese] {line.strip()}</d>' in prompt
                        else:
                            assert line.strip() in prompt
            for field in ('firstFrameObjectKey', 'lastFrameObjectKey'):
                with Image.open(io.BytesIO(objects[asset[field]])) as image:
                    assert image.format == 'JPEG'
            assert objects[asset['objectKey']]
        restored = (await client.get(f'/api/projects/{pid}')).json()
        count = len(fixture['script']['shots'])
        assert len(restored['visualAssets']) == count
        assert all(asset['valid'] and asset.get('downloadUrl')
                   for asset in restored['visualAssets'])
        expected = (['text'] if prompt_mode == 'local-skill' else [])
        assert events == (expected + ['submit', 'poll', 'download']) * count
