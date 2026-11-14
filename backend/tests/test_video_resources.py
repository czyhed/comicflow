from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import ProjectRecord
from comicflow.infrastructure.memory import create_memory_runtime


class Store:
    def __init__(self):
        self.calls = []
        self.missing = set()
        self.broken = False

    async def exists(self, key):
        self.calls.append(('head', key))
        if self.broken:
            raise RuntimeError('secret upstream failure')
        return key not in self.missing

    async def presigned_get_url(self, key, expires_in=900):
        self.calls.append(('play', key))
        return f'https://assets.invalid/{key}?signature={len(self.calls)}'

    async def presigned_download_url(self, key, filename, expires_in=900):
        self.calls.append(('download', key, filename))
        return f'https://assets.invalid/{key}?attachment={len(self.calls)}'


@pytest.fixture
async def library(monkeypatch):
    monkeypatch.setenv('COMICFLOW_RUNTIME', 'memory')
    runtime = create_memory_runtime()
    store = Store()
    runtime.pipeline._asset_store = store
    project = {
        'id': 'p1', 'version': 4, 'ownerUserId': 'alice',
        'script': {'title': '雨夜', 'shots': [{'id': 's1', 'title': '推门入店'}]},
        'visualAssets': [
            {'id': 'old', 'shotId': 's1', 'mediaType': 'video', 'valid': False,
             'objectKey': 'old.mp4', 'sourceUrl': 'https://secret.invalid/token'},
            {'id': 'current', 'shotId': 's1', 'mediaType': 'video', 'valid': True,
             'objectKey': 'new.mp4', 'createdAt': '2026-09-18T00:00:00Z',
             'firstFrameObjectKey': 'first.jpg', 'modelVersion': 'MiniMax-H3'},
            {'id': 'gone', 'shotId': 'deleted', 'mediaType': 'video', 'valid': False,
             'sourceUrl': 'https://expired.invalid/token'},
            {'id': 'image', 'mediaType': 'image', 'valid': True},
        ],
        'exportManifest': {'objectKeys': {'video.mp4': 'export.mp4'}},
    }
    await runtime.pipeline._repository.save(ProjectRecord(deepcopy(project), {}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test', headers={'X-User-Id': 'alice'}) as client:
        yield client, runtime, store, project


async def test_history_list_is_paginated_metadata_only_and_read_only(library):
    client, runtime, store, original = library
    response = await client.get('/api/projects/p1/video-resources?kind=shot&limit=2')
    assert response.status_code == 200
    body = response.json()
    assert body['total'] == 3
    assert [a['id'] for a in body['items']] == ['current', 'gone']
    assert body['items'][0]['status'] == 'current'
    assert body['items'][1]['sourceAvailable'] is False
    old = (await client.get('/api/projects/p1/video-resources?kind=shot&offset=2')).json()
    assert old['items'][0]['id'] == 'old'
    assert old['items'][0]['createdAt'] is None
    assert old['items'][0]['status'] == 'historical'
    assert 'objectKey' not in response.text and 'secret.invalid' not in response.text
    assert store.calls == []
    assert (await runtime.pipeline._repository.get('p1')).project == original


async def test_access_history_renews_and_download_does_not_adopt(library):
    client, runtime, store, original = library
    path = '/api/projects/p1/video-resources/old/access'
    first = await client.get(path)
    second = await client.get(path)
    assert first.status_code == second.status_code == 200
    assert first.json()['url'] != second.json()['url']
    assert first.headers['cache-control'] == 'no-store'
    download = await client.get(path + '?download=true')
    assert download.status_code == 200
    assert store.calls[-1] == ('download', 'old.mp4', 'video-old.mp4')
    assert (await runtime.pipeline._repository.get('p1')).project == original


@pytest.mark.parametrize('path', ['/video-resources', '/video-resources/old/access'])
@pytest.mark.parametrize('user', ['bob', ''])
async def test_unauthorized_cannot_list_or_sign(library, path, user):
    client, _, store, _ = library
    response = await client.get('/api/projects/p1' + path, headers={'X-User-Id': user})
    assert response.status_code == 403
    assert store.calls == []


async def test_missing_vs_storage_failure_and_untrusted_url(library):
    client, _, store, _ = library
    store.missing.add('old.mp4')
    assert (await client.get('/api/projects/p1/video-resources/old/access')).json() == {
        'error': 'RESOURCE_FILE_MISSING'}
    store.broken = True
    response = await client.get('/api/projects/p1/video-resources/current/access')
    assert response.status_code == 503
    assert response.json() == {'error': 'RESOURCE_STORAGE_UNAVAILABLE'}
    store.calls.clear()
    assert (await client.get('/api/projects/p1/video-resources/gone/access')).status_code == 409
    arbitrary = await client.get('/api/projects/p1/video-resources/arbitrary-key/access')
    assert arbitrary.status_code == 404
    assert store.calls == []


async def test_filters_exports_and_invalid_pagination(library):
    client, _, _, _ = library
    response = await client.get('/api/projects/p1/video-resources?shot_id=s1&status=current')
    assert [a['id'] for a in response.json()['items']] == ['current']
    exports = (await client.get('/api/projects/p1/video-resources?kind=export')).json()
    assert [a['id'] for a in exports['items']] == ['export:current']
    assert (await client.get('/api/projects/p1/video-resources?limit=101')).status_code == 422
    assert (await client.get('/api/projects/p1/video-resources?offset=-1')).status_code == 422


async def test_missing_poster_does_not_block_video_and_export_uses_saved_key(library):
    client, _, store, _ = library
    store.missing.add('first.jpg')
    response = await client.get('/api/projects/p1/video-resources/current/access')
    assert response.status_code == 200
    assert response.json()['posterUrl'] is None
    assert 'new.mp4' in response.json()['url']
    exported = await client.get('/api/projects/p1/video-resources/export:current/access')
    assert 'export.mp4' in exported.json()['url']


async def test_candidate_and_explicit_stale_metadata_filters(library):
    client, runtime, store, original = library
    project = deepcopy(original)
    project['visualAssets'][0]['invalidatedReason'] = 'input-changed'
    project['visualAssets'][2]['status'] = 'candidate'
    await runtime.pipeline._repository.save(ProjectRecord(project, {}))
    for status, expected in [('stale', 'old'), ('candidate', 'gone')]:
        result = await client.get(f'/api/projects/p1/video-resources?status={status}')
        assert [a['id'] for a in result.json()['items']] == [expected]
    assert store.calls == []
