from copy import deepcopy

import pytest
from comicflow.api.app import create_app
from comicflow.domain.errors import DomainError
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient
from test_composition_module_contract import ArtifactComposer, SigningStore, create_project


async def prepared():
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    pid = await create_project(pipeline)
    record = await pipeline._repository.get(pid)
    record.project.update(
        script={'scenes': [], 'shots': [
            {'id': 'a', 'order': 1, 'durationSec': 2},
            {'id': 'b', 'order': 2, 'durationSec': 2},
            {'id': 'c', 'order': 3, 'durationSec': 2},
        ]},
        visualAssets=[{'id': f'v-{sid}', 'shotId': sid, 'valid': True,
                       'provider': 'minimax', 'mediaType': 'video'} for sid in ['a', 'b']],
        exportManifest={'files': ['original.mp4']},
        downstreamInvalidated=True,
        stage='storyboard-ready',
        generationSession={'status': 'ready'},
    )
    record.project['input']['mode'] = 'automatic'
    await pipeline._repository.save(record)
    pipeline._composition_provider = ArtifactComposer('offline')
    pipeline._asset_store = SigningStore()
    return runtime, pid


async def test_partial_filters_orders_and_keeps_complete_export_and_project():
    runtime, pid = await prepared()
    pipeline = runtime.pipeline
    before = (await pipeline._repository.get(pid)).project
    with pytest.raises(DomainError, match='ASSETS_INCOMPLETE'):
        await pipeline.request_composition(pid, expected_version=1)
    job = await pipeline.request_composition(pid, expected_version=1, shot_ids=['b', 'a'])
    assert job['shotIds'] == ['a', 'b']
    done = await pipeline.run_job(job['id'])
    assert done['status'] == 'succeeded'
    seen = pipeline._composition_provider.calls[0]
    assert [s['id'] for s in seen['script']['shots']] == ['a', 'b']
    assert [v['shotId'] for v in seen['visualAssets']] == ['a', 'b']
    after = (await pipeline._repository.get(pid)).project
    for key in ['script', 'exportManifest', 'stage', 'generationSession', 'downstreamInvalidated']:
        assert after[key] == before[key]
    manifest = await pipeline.get_export_manifest(pid, job_id=job['id'])
    assert manifest['scope'] == 'selected' and manifest['shotIds'] == ['a', 'b']
    assert manifest['jobId'] == job['id']
    assert all(f'/previews/{job["id"]}/' in key for key in manifest['objectKeys'].values())
    assert (await pipeline.get_export_manifest(pid)) == before['exportManifest']


@pytest.mark.parametrize('ids', [[], ['missing'], ['a', 'a']])
async def test_invalid_selection_has_no_credit_or_job_changes(ids):
    runtime, pid = await prepared()
    before = await runtime.pipeline._repository.get(pid)
    with pytest.raises(DomainError, match='COMPOSITION_SHOTS_INVALID'):
        await runtime.pipeline.request_composition(pid, expected_version=1, shot_ids=ids)
    assert await runtime.pipeline._repository.get(pid) == before


async def test_selected_missing_assets_are_still_rejected():
    runtime, pid = await prepared()
    with pytest.raises(DomainError) as error:
        await runtime.pipeline.request_composition(pid, expected_version=1, shot_ids=['c'])
    assert error.value.code == 'ASSETS_INCOMPLETE'
    assert error.value.detail['missingVisualShotIds'] == ['c']
    record = await runtime.pipeline._repository.get(pid)
    record.project['visualAssets'][0]['provider'] = 'other'
    record.project['script']['shots'][0]['dialogue'] = '你好'
    await runtime.pipeline._repository.save(record)
    with pytest.raises(DomainError) as error:
        await runtime.pipeline.request_composition(pid, expected_version=1, shot_ids=['a'])
    assert error.value.detail['missingAudioShotIds'] == ['a']


async def test_partial_http_contract_permissions_and_idempotency():
    runtime, pid = await prepared()
    await runtime.pipeline.claim_project(pid, user_id='owner')
    async with AsyncClient(transport=ASGITransport(app=create_app(runtime)),
                           base_url='http://test') as client:
        headers = {'X-User-Id': 'owner'}
        body = {'expectedVersion': 1, 'shotIds': ['b', 'a'], 'idempotencyKey': 'partial'}
        response = await client.post(f'/api/projects/{pid}/composition', json=body, headers=headers)
        assert response.status_code == 202
        job = response.json()
        assert job['shotIds'] == ['a', 'b']
        repeat = await client.post(f'/api/projects/{pid}/composition', json=body, headers=headers)
        assert repeat.json() == job
        await runtime.pipeline.run_job(job['id'])
        url = f'/api/projects/{pid}/export?job_id={job["id"]}'
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url, headers={'X-User-Id': 'other'})).status_code == 403
        result = await client.get(url, headers=headers)
        assert result.status_code == 200 and result.json()['scope'] == 'selected'
        assert (await client.get(f'/api/projects/{pid}/export?job_id=missing',
                                 headers=headers)).status_code == 404


async def test_partial_failure_keeps_generation_session_and_previous_export():
    runtime, pid = await prepared()
    pipeline = runtime.pipeline
    before = deepcopy((await pipeline._repository.get(pid)).project)

    class Broken(ArtifactComposer):
        async def compose(self, project):
            raise RuntimeError('COMPOSITION_MEDIA_UNREADABLE')

    pipeline._composition_provider = Broken('offline')
    job = await pipeline.request_composition(pid, expected_version=1, shot_ids=['a'])
    result = await pipeline.run_job(job['id'])
    assert result['status'] == 'failed'
    after = (await pipeline._repository.get(pid)).project
    assert after['generationSession'] == before['generationSession']
    assert after['exportManifest'] == before['exportManifest']
