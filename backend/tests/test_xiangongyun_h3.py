import base64

import httpx
import pytest
from comicflow.domain.errors import DomainError
from comicflow.providers.h3_context_ir import compile_chinese_intent
from comicflow.providers.h3_errors import H3ResponseError
from comicflow.providers.h3_inputs import text_metadata
from comicflow.providers.model_protocols import validate_config
from comicflow.providers.xiangongyun_h3 import XiangongyunH3Provider


class Store:
    def __init__(self):
        self.writes = []

    async def put_bytes(self, object_key, content, content_type):
        self.writes.append((object_key, content, content_type))
        return object_key


@pytest.mark.asyncio
async def test_submit_reference_poll_download_and_resume_without_resubmit():
    import io

    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (256, 256)).save(image, 'PNG')
    url = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers['authorization'] == 'Bearer secret'
        if request.url.path == '/api/v1/jobs' and request.method == 'POST':
            body = request.content
            assert b'name="task_mode"' in body and b'ref2va' in body
            assert b'name="reference_images"' in body
            assert b'name="reference_manifest"' in body
            assert b'"mention": "cf_' in body
            assert b'@cf_' in body and b'<Picture 1>' not in body
            assert b'name="compile_prompt"' in body and b'false' in body
            assert b'name="width"' in body and b'544' in body
            return httpx.Response(202, json={'data': {'prompt_id': 'job-1'}})
        if request.url.path == '/api/v1/jobs/job-1':
            return httpx.Response(200, json={'data': {
                'status': 'completed', 'terminal': True, 'succeeded': True,
                'outputs': [{'download_url': '/api/v1/output?filename=one.mp4'}],
            }})
        assert request.url.path == '/api/v1/output'
        return httpx.Response(200, content=b'video', headers={'content-type': 'video/mp4'})

    store = Store()
    provider = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test', model='MiniMax-H3',
        prompt_mode='context-ir', asset_store=store, transport=httpx.MockTransport(handle),
        poll_interval_seconds=0,
    )
    checkpoints = []

    async def checkpoint(stage, fields):
        checkpoints.append((stage, fields))

    shot = {'id': 'shot-1', 'visualDescription': '雨夜街头奔跑', 'durationSec': 5,
            'referenceImages': [{'id': 'scene-1', 'url': url}]}
    result = await provider.generate(shot, [], checkpoint=checkpoint)
    assert result['objectKey'] == 'videos/shot-1/job-1.mp4'
    assert store.writes[0][1] == b'video'
    assert ('polling', {'taskId': 'job-1'}) in checkpoints
    assert result['promptExecution']['mode'] == 'context-ir'
    assert '@cf_' in result['h3Prompt']
    assert '<Picture 1>' not in result['h3Prompt']
    before = len([r for r in requests if r.method == 'POST'])
    await provider.generate(shot, [], resume={
        'taskId': 'job-1', 'compiled': {'plan': {'durationSec': 5, 'mode': 'ref2va'},
                                      'execution': {}, 'prompt': 'saved'},
    })
    assert len([r for r in requests if r.method == 'POST']) == before


@pytest.mark.asyncio
async def test_cross_origin_output_never_receives_key():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(202, json={'data': {'prompt_id': 'job-2'}})
        return httpx.Response(200, json={'data': {
            'status': 'completed', 'terminal': True, 'succeeded': True,
            'outputs': [{'download_url': 'https://attacker.test/api/v1/output'}],
        }})

    provider = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test', model='MiniMax-H3',
        prompt_mode='context-ir', transport=httpx.MockTransport(handle),
    )
    with pytest.raises(H3ResponseError):
        await provider.generate({'id': 's', 'visualDescription': '雨夜街头', 'durationSec': 5}, [])
    assert all(r.url.host == 'instance.test' for r in requests)


def test_protocol_rejects_unknown_profiles():
    assert validate_config('xiangongyun-h3', {})['resolution'] == '0.5P'
    for config in ({'resolution': '768P'}, {'inferenceProfile': 'unknown'},
                   {'submitPath': '//evil.test'}, {'inferenceProfile': []}):
        with pytest.raises(DomainError):
            validate_config('xiangongyun-h3', config)


@pytest.mark.asyncio
async def test_first_frame_upload_and_failed_task():
    import io

    from PIL import Image

    image = io.BytesIO()
    Image.new('RGB', (256, 256)).save(image, 'PNG')
    url = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == 'POST':
            assert b'name="task_mode"' in request.content and b'i2va' in request.content
            assert b'name="first_frame"' in request.content
            assert b'<Picture 1>' not in request.content
            assert b'name="reference_manifest"' not in request.content
            return httpx.Response(202, json={'data': {'prompt_id': 'job-3'}})
        return httpx.Response(200, json={'data': {
            'status': 'error', 'terminal': True, 'succeeded': False, 'outputs': [],
        }})

    provider = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test', model='MiniMax-H3',
        prompt_mode='context-ir', transport=httpx.MockTransport(handle),
    )
    with pytest.raises(RuntimeError, match='VIDEO_GENERATION_FAILED') as caught:
        await provider.generate({
            'id': 's', 'visualDescription': '雨夜街头', 'durationSec': 5,
            'firstFrameUrl': url,
        }, [])
    assert caught.value.detail['taskId'] == 'job-3'
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_download_redirect_rejected_without_following():
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(202, json={'data': {'prompt_id': 'job-4'}})
        if request.url.path == '/api/v1/jobs/job-4':
            return httpx.Response(200, json={'data': {
                'status': 'completed', 'terminal': True, 'succeeded': True,
                'outputs': [{'download_url': '/api/v1/output?filename=one.mp4'}],
            }})
        return httpx.Response(302, headers={'location': 'https://attacker.test/output'})

    provider = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test', model='MiniMax-H3',
        prompt_mode='context-ir', transport=httpx.MockTransport(handle),
    )
    with pytest.raises(H3ResponseError):
        await provider.generate({'id': 's', 'visualDescription': '雨夜街头'}, [])
    assert len(requests) == 3
    assert all(r.url.host == 'instance.test' for r in requests)


def test_preview_describes_local_compilation_without_platform_optimization():
    provider = XiangongyunH3Provider(api_key='secret', base_url='https://instance.test')
    shot = {'id': 's', 'visualDescription': '雨夜街头', 'referenceImages': [
        {'id': 'scene', 'url': 'https://assets.test/scene.png'},
    ]}
    preview = provider.prepare_preview(shot, [])
    assert preview['prompt']['platformOptimization'] is False
    assert preview['prompt']['rules']['useContextIr'] is False
    assert preview['parameters']['compilePrompt'] is False
    assert preview['calls'] == {'text': 0, 'video': 1}
    assert '<Picture 1>' not in preview['prompt']['text']
    assert '@' in preview['prompt']['text']
    assert '优云' not in provider.prompt_description


async def test_prepared_checkpoint_reloads_images_before_first_submission():
    import io

    from PIL import Image

    image = io.BytesIO()
    Image.new('RGB', (256, 256)).save(image, 'PNG')
    shot = {'id': 's', 'visualDescription': '雨夜街头', 'referenceImages': [{
        'id': 'scene', 'objectKey': 'scenes/one.png', 'url': 'https://assets.test/one.png',
    }]}
    compiled = text_metadata(compile_chinese_intent(shot, []))
    reads, requests = [], []

    class ImageStore(Store):
        async def get_bytes(self, key, limit):
            reads.append(key)
            return image.getvalue()

    def handle(request):
        requests.append(request)
        assert b'name="reference_images"' in request.content
        assert image.getvalue() in request.content
        return httpx.Response(401, json={'error': 'secret upstream content'})

    provider = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test', prompt_mode='context-ir',
        asset_store=ImageStore(), transport=httpx.MockTransport(handle),
    )
    with pytest.raises(RuntimeError, match='PROVIDER_AUTH_FAILED') as caught:
        await provider.generate(shot, [], resume={'compiled': compiled})
    assert reads == ['scenes/one.png'] and len(requests) == 1
    assert 'secret' not in str(caught.value.detail)


def test_job_configuration_tracks_resolution_and_inference_profile():
    from comicflow.production.visual_preflight import adapter_identity

    default = XiangongyunH3Provider(api_key='secret', base_url='https://instance.test')
    high = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test', resolution='1.0P',
    )
    quality = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test',
        inference_profile='quality_av_sol_gpu_te',
    )
    assert adapter_identity(default) != adapter_identity(high)
    assert adapter_identity(default) != adapter_identity(quality)


async def test_catalog_binding_builds_xiangongyun_adapter_without_network():
    import json

    from comicflow.providers.model_registry import (
        MemoryRegistryRepository,
        ModelRegistry,
        SecretCipher,
    )
    from comicflow.providers.model_selection import ModelSelection

    registry = ModelRegistry(MemoryRegistryRepository(), SecretCipher.ephemeral())
    view = await registry.mutate('connection', None, {
        'revision': 0, 'name': '仙宫云', 'baseUrl': 'https://instance.test',
        'apiKey': 'private-key',
    })
    view = await registry.mutate('model', None, {
        'revision': view['revision'], 'name': 'H3', 'connectionId': view['connections'][0]['id'],
        'protocol': 'xiangongyun-h3', 'model': 'MiniMax-H3', 'enabled': True, 'config': {},
    })
    await registry.bind({
        'revision': view['revision'], 'bindings': {'video': view['models'][0]['id']},
    })
    provider = ModelSelection(await registry.snapshot(), None).provider('video', None)
    assert isinstance(provider, XiangongyunH3Provider)
    assert provider.prepare_preview({'id': 's', 'action': '推门'}, [])['calls']['text'] == 0
    assert 'private-key' not in json.dumps(await registry.view())


@pytest.mark.parametrize('lost_submit', [False, True])
async def test_durable_job_preserves_unknown_or_recovers_existing_task(lost_submit):
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='女子冒雨走进便利店。', duration_sec=30, mode='import_story',
    ))
    pid = created['project']['id']
    record = await pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{
        'id': 's', 'durationSec': 5, 'action': '推门进入', 'characterIds': [],
    }]}
    await pipeline._repository.save(record)
    calls = []
    fail_poll = True

    def handle(request):
        calls.append(request.method)
        if request.method == 'POST':
            if lost_submit:
                raise httpx.ReadTimeout('private-key', request=request)
            return httpx.Response(202, json={'data': {'prompt_id': 'saved-job'}})
        if request.url.path.endswith('/saved-job'):
            if fail_poll:
                raise httpx.ReadTimeout('private-key', request=request)
            return httpx.Response(200, json={'data': {
                'status': 'completed', 'terminal': True, 'succeeded': True,
                'outputs': [{'download_url': '/api/v1/output?filename=one.mp4'}],
            }})
        return httpx.Response(200, content=b'video', headers={'content-type': 'video/mp4'})

    pipeline.set_video_provider(XiangongyunH3Provider(
        api_key='private-key', base_url='https://instance.test',
        transport=httpx.MockTransport(handle),
    ))
    job = await pipeline.request_video_job(
        pid, 's', expected_version=record.project['version'], operation_id='click',
    )
    failed = await pipeline.run_video_job(job['id'])
    assert failed['status'] == ('unknown' if lost_submit else 'recoverable')
    if lost_submit:
        with pytest.raises(DomainError):
            await pipeline.recover_video_job(pid, job['id'])
    else:
        assert failed['taskId'] == 'saved-job'
        fail_poll = False
        await pipeline.recover_video_job(pid, job['id'])
        finished = await pipeline.run_video_job(job['id'])
        assert finished['status'] == 'succeeded'
        assert finished['result']['adopted'] is False
    assert calls.count('POST') == 1
    assert 'private-key' not in str(await pipeline.list_video_jobs(pid))


@pytest.mark.parametrize('mode,frame_keys', [
    ('t2va', []), ('i2va', ['first']), ('l2va', ['last']), ('fl2va', ['first', 'last']),
    ('ref2va', []),
])
async def test_all_input_modes_and_reference_order(mode, frame_keys):
    import io
    import json

    from comicflow.providers.h3_inputs import prepare_images
    from PIL import Image

    image = io.BytesIO()
    Image.new('RGB', (256, 256)).save(image, 'PNG')
    url = 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
    shot = {'id': 's', 'action': '向前走', 'generationMode': mode, 'aspectRatio': '16:9',
            **{f'{key}FrameUrl': url for key in frame_keys}}
    if mode == 'ref2va':
        shot['referenceImages'] = [{'id': f'scene-{i}', 'url': url} for i in range(2)]
    shot, characters = await prepare_images(shot, [], None)
    provider = XiangongyunH3Provider(api_key='secret', base_url='https://instance.test')
    compiled = compile_chinese_intent(shot, characters)
    fields, files = provider._submission(shot, compiled)
    preview = provider.prepare_preview(shot, characters)
    assert fields['task_mode'] == mode
    assert fields['width'] == '960' and fields['height'] == '544'
    assert fields['compile_prompt'] == 'false'
    assert preview['parameters']['ratio'] == fields['aspect_ratio']
    assert preview['prompt']['text'] == fields['prompt']
    if mode == 'ref2va':
        manifest = json.loads(fields['reference_manifest'])
        assert [m['external_id'] for m in manifest] == ['scene-0', 'scene-1']
        assert [m['index'] for m in manifest] == [0, 1]
        assert all('@' + m['mention'] in fields['prompt'] for m in manifest)
        assert [f[0] for f in files] == ['reference_images', 'reference_images']
        assert [r['label'] for r in preview['images']] == ['@' + m['mention'] for m in manifest]
    else:
        assert 'reference_manifest' not in fields
        assert [f[0] for f in files] == [f'{key}_frame' for key in frame_keys]


@pytest.mark.parametrize('fault', ['missing-success', 'html-output', 'unknown-status', 'timeout'])
async def test_malformed_results_remain_recoverable_with_task_id(fault):
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == 'POST':
            return httpx.Response(202, json={'prompt_id': 'known'})
        if request.url.path == '/api/v1/output':
            return httpx.Response(200, text='<html>private-key</html>',
                                  headers={'content-type': 'text/html'})
        body = {'status': 'completed', 'terminal': True, 'succeeded': True,
                'outputs': [{'download_url': '/api/v1/output?filename=one.mp4'}]}
        if fault == 'missing-success':
            body.pop('succeeded')
        elif fault in {'unknown-status', 'timeout'}:
            body = {'status': 'unrecognized' if fault == 'unknown-status' else 'queued',
                    'terminal': False}
        return httpx.Response(200, json=body)

    provider = XiangongyunH3Provider(
        api_key='private-key', base_url='https://instance.test',
        timeout_seconds=0.001, poll_interval_seconds=0, transport=httpx.MockTransport(handle),
    )
    with pytest.raises(H3ResponseError) as caught:
        await provider.generate({'id': 's', 'action': '走向门口'}, [])
    assert caught.value.detail['taskId'] == 'known'
    assert 'private-key' not in str(caught.value.detail)
    assert sum(r.method == 'POST' for r in requests) == 1


async def test_reference_url_without_local_bytes_fails_before_text_expansion():
    from unittest.mock import AsyncMock

    writer = AsyncMock()
    provider = XiangongyunH3Provider(
        api_key='secret', base_url='https://instance.test',
        prompt_mode='local-skill', prompt_writer=writer,
    )
    with pytest.raises(RuntimeError, match='H3_REFERENCE_UNREADABLE'):
        await provider.generate({'id': 's', 'action': '推门', 'referenceImages': [
            {'id': 'ref', 'url': 'https://assets.test/one.png'},
        ]}, [])
    writer.write.assert_not_awaited()
