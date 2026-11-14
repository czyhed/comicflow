import httpx
import pytest
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
from comicflow.providers.error_mapping import map_provider_error


@pytest.mark.parametrize('phase', ['submit', 'poll'])
@pytest.mark.parametrize('supplier_code,http_status,expected', [
    ('InvalidParameter', 400, 'VIDEO_REQUEST_INVALID'),
    ('AllocationQuota.FreeTierOnly', 403, 'VIDEO_QUOTA_EXHAUSTED'),
    ('Throttling', 429, 'VIDEO_RATE_LIMITED'),
    ('InputDataInspectionFailed', 400, 'VIDEO_CONTENT_REJECTED'),
    ('InvalidApiKey', 401, 'PROVIDER_AUTH_FAILED'),
])
async def test_supplier_failures_keep_specific_code_without_retry(
    phase, supplier_code, http_status, expected, caplog,
):
    calls = []

    def handler(request):
        calls.append(request.method)
        if phase == 'submit':
            return httpx.Response(http_status, json={
                'code': supplier_code, 'request_id': 'request-123',
                'message': 'private-url-or-secret-must-not-be-logged',
            })
        if request.method == 'POST':
            return httpx.Response(200, json={'output': {'task_id': 'task-123'}})
        return httpx.Response(200, json={
            'request_id': 'request-123',
            'output': {'task_status': 'FAILED', 'code': supplier_code,
                       'message': 'private-url-or-secret-must-not-be-logged'},
        })

    provider = BailianImageToVideoProvider(
        api_key='offline', model='wan2.7-i2v', resolution='720P',
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RuntimeError, match=f'^{expected}$') as failure:
        await provider.generate({
            'id': 's1', 'durationSec': 5, 'visualDescription': '雨夜车站',
            'firstFrameUrl': 'https://assets.test/frame.png',
        }, [])
    assert map_provider_error(str(failure.value)) == expected
    assert calls == (['POST'] if phase == 'submit' else ['POST', 'GET'])
    assert supplier_code in caplog.text
    assert 'request-123' in caplog.text
    assert 'private-url-or-secret' not in caplog.text


@pytest.mark.parametrize('supplier_code,status,expected', [
    ('InvalidParameter', 400, 'VIDEO_REQUEST_INVALID'),
    ('AllocationQuota.FreeTierOnly', 409, 'VIDEO_QUOTA_EXHAUSTED'),
    ('Throttling', 429, 'VIDEO_RATE_LIMITED'),
    ('InputDataInspectionFailed', 422, 'VIDEO_CONTENT_REJECTED'),
    ('InternalError', 503, 'PROVIDER_UNAVAILABLE'),
])
async def test_failed_video_task_reaches_api_without_writing_asset(supplier_code, status, expected):
    from comicflow.api.app import create_app
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'output': {'task_id': 'task-123'}})
        return httpx.Response(200, json={'output': {
            'task_status': 'FAILED', 'code': supplier_code, 'message': 'private-supplier-detail',
        }})

    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，小雨在车站等待她的姐姐，远处传来汽笛声。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await pipeline._repository.get(pid)
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1']}],
        'shots': [{'id': 's1', 'durationSec': 5, 'visualDescription': '雨夜车站',
                   'firstFrameUrl': 'https://assets.test/frame.png', 'characterIds': []}],
    }
    await pipeline._repository.save(record)
    version = record.project['version']
    pipeline.set_video_provider(BailianImageToVideoProvider(
        api_key='offline', model='wan2.7-i2v', resolution='720P',
        transport=httpx.MockTransport(handler),
    ))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        result = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': version,
        })
    assert result.status_code == status, result.text
    assert result.json()['error'] == expected
    assert 'private-supplier-detail' not in result.text
    assert calls == ['POST', 'GET']
    saved = await pipeline._repository.get(pid)
    assert not saved.project.get('visualAssets')
    assert saved.project['version'] == version
