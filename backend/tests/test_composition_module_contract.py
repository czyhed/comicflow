"""Characterize existing composition entry points before and after extraction."""
from copy import copy, deepcopy

import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def create_project(pipeline):
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜车站，两人相遇后各自离开。',
        duration_sec=30, mode='import_story',
    ))
    return created['project']['id']


class ArtifactComposer:
    def __init__(self, label):
        self.label = label
        self.calls = []

    async def compose(self, project):
        self.calls.append(deepcopy(project))
        return {
            'projectId': project['id'], 'format': self.label,
            'files': ['video.mp4', 'cover.jpg', 'subtitles.srt'],
            'artifacts': {'video.mp4': b'video', 'cover.jpg': b'cover',
                          'subtitles.srt': b'subtitles'},
        }


class SigningStore:
    def __init__(self):
        self.uploads = {}
        self.serial = 0

    async def put_bytes(self, key, content, content_type):
        self.uploads[key] = (content, content_type)
        return key

    async def presigned_get_url(self, key, expires_in=900):
        self.serial += 1
        return f'https://offline.invalid/{key}?signature={self.serial}'


async def test_scoped_composition_uses_current_dependencies_and_revision():
    pipeline = create_memory_runtime().pipeline
    first, second = ArtifactComposer('first'), ArtifactComposer('second')
    pipeline._composition_provider = first
    pipeline._model_config_revision = 11
    scoped = copy(pipeline)
    scoped._composition_provider = second
    scoped._model_config_revision = 12
    first_id, second_id = await create_project(pipeline), await create_project(scoped)
    a = await pipeline.request_composition(first_id, expected_version=1, idempotency_key='a')
    b = await scoped.request_composition(second_id, expected_version=1, idempotency_key='b')
    assert (a['modelConfigRevision'], b['modelConfigRevision']) == (11, 12)
    assert (await pipeline.run_job(a['id']))['exportManifest']['format'] == 'first'
    assert (await scoped.run_job(b['id']))['exportManifest']['format'] == 'second'
    # Also exercise dependency replacement after the first operation on this instance.
    pipeline._composition_provider = second
    pipeline._model_config_revision = 13
    third_id = await create_project(pipeline)
    c = await pipeline.request_composition(third_id, expected_version=1)
    assert c['modelConfigRevision'] == 13
    assert (await pipeline.run_job(c['id']))['exportManifest']['format'] == 'second'
    assert [p['id'] for p in first.calls] == [first_id]
    assert [p['id'] for p in second.calls] == [second_id, third_id]


async def test_export_refreshes_signed_links_without_writing_or_composing_again():
    pipeline = create_memory_runtime().pipeline
    pid = await create_project(pipeline)
    composer, store = ArtifactComposer('offline'), SigningStore()
    pipeline._composition_provider = composer
    pipeline._asset_store = store
    job = await pipeline.request_composition(pid, expected_version=1)
    done = await pipeline.run_job(job['id'])
    before = await pipeline._repository.get(pid)
    first = await pipeline.get_export_manifest(pid)
    second = await pipeline.get_export_manifest(pid)
    assert first['downloads'] != second['downloads'] != done['exportManifest']['downloads']
    assert first['objectKeys'] == second['objectKeys']
    assert len(composer.calls) == 1
    assert await pipeline._repository.get(pid) == before
    assert store.uploads == {
        f'exports/{pid}/video.mp4': (b'video', 'video/mp4'),
        f'exports/{pid}/cover.jpg': (b'cover', 'image/jpeg'),
        f'exports/{pid}/subtitles.srt': (b'subtitles', 'application/x-subrip'),
    }
    assert 'artifacts' not in first


@pytest.mark.parametrize('failure', ['EXPORT_PACKAGE_INCOMPLETE', 'EXPORT_ARTIFACT_MISSING'])
async def test_invalid_export_releases_once_and_preserves_previous_manifest(failure):
    pipeline = create_memory_runtime().pipeline
    pid = await create_project(pipeline)
    old = {'files': ['old.mp4'], 'objectKeys': {'old.mp4': 'old-key'}}
    record = await pipeline._repository.get(pid)
    record.project['exportManifest'] = deepcopy(old)
    record.project['input']['mode'] = 'automatic'
    record.project['stage'] = 'composition-queued'
    await pipeline._repository.save(record)

    class BrokenComposer(ArtifactComposer):
        async def compose(self, project):
            manifest = await super().compose(project)
            if failure == 'EXPORT_PACKAGE_INCOMPLETE':
                manifest['files'].remove('subtitles.srt')
            else:
                del manifest['artifacts']['subtitles.srt']
            return manifest

    pipeline._composition_provider = BrokenComposer('broken')
    pipeline._asset_store = SigningStore()
    job = await pipeline.request_composition(pid, expected_version=1)
    for _ in range(2):
        result = await pipeline.run_job(job['id'])
        assert result['status'] == 'failed' and result['error'] == failure
    record = await pipeline._repository.get(pid)
    assert record.project['exportManifest'] == old
    assert record.project['generationSession']['status'] == 'waiting-retry'
    assert sum(e['type'] == 'release' for e in record.project['creditLedger']) == 1
    assert not any(e['type'] == 'settlement' for e in record.project['creditLedger'])


async def test_composition_routes_keep_idempotency_auth_and_cancel_job_ownership():
    runtime = create_memory_runtime()
    pid = await create_project(runtime.pipeline)
    other_pid = await create_project(runtime.pipeline)
    await runtime.pipeline.claim_project(pid, user_id='owner')
    await runtime.pipeline.claim_project(other_pid, user_id='owner')
    other_job = await runtime.pipeline.request_composition(other_pid, expected_version=1)
    async with AsyncClient(transport=ASGITransport(app=create_app(runtime)),
                           base_url='http://test') as client:
        request = {'expectedVersion': 1, 'idempotencyKey': 'compose-once'}
        forbidden = await client.post(f'/api/projects/{pid}/composition', json=request,
                                      headers={'X-User-Id': 'other'})
        assert forbidden.status_code == 403
        owner = {'X-User-Id': 'owner'}
        first = await client.post(f'/api/projects/{pid}/composition', json=request, headers=owner)
        repeated = await client.post(
            f'/api/projects/{pid}/composition', json=request, headers=owner,
        )
        assert first.status_code == repeated.status_code == 202
        assert first.json() == repeated.json()
        job_id = first.json()['id']
        conflict = await client.post(f'/api/projects/{pid}/composition', headers=owner,
                                     json={**request, 'expectedVersion': 0})
        assert conflict.status_code == 409 and conflict.json()['error'] == 'VERSION_CONFLICT'
        for url in (f'/api/projects/{pid}/export', f'/api/projects/{pid}/jobs/{job_id}/cancel'):
            method = client.get if url.endswith('/export') else client.post
            assert (await method(url)).status_code == 401
            assert (await method(url, headers={'X-User-Id': 'other'})).status_code == 403
        cross = await client.post(
            f'/api/projects/{pid}/jobs/{other_job["id"]}/cancel', headers=owner,
        )
        assert cross.status_code == 404 and cross.json()['error'] == 'JOB_NOT_FOUND'
        not_ready = await client.get(f'/api/projects/{pid}/export', headers=owner)
        assert not_ready.status_code == 409 and not_ready.json()['error'] == 'EXPORT_NOT_READY'
        cancelled = await client.post(f'/api/projects/{pid}/jobs/{job_id}/cancel', headers=owner)
        assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
        assert (await runtime.pipeline.run_job(job_id))['status'] == 'cancelled'
        snapshot = await runtime.pipeline.get_snapshot(pid, user_id='owner')
        assert len(snapshot['jobs']) == 1
        assert sum(e['type'] == 'reservation' for e in snapshot['creditLedger']) == 1
        assert sum(e['type'] == 'release' for e in snapshot['creditLedger']) == 1
