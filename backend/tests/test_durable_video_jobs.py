import asyncio
import json

import httpx
import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.database import (
    Base,
    SqlAlchemyProjectRepository,
    create_session_factory,
)
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.infrastructure.video_jobs import SqlVideoJobStore
from comicflow.providers.minimax_h3 import MinimaxH3Provider


@pytest.fixture
async def video():
    runtime = create_memory_runtime()
    p = runtime.pipeline
    created = await p.create_project(CreateProject(input_type='story',
        story='女子冒雨走进便利店，寻找失踪的朋友。', duration_sec=30, mode='import_story'))
    pid = created['project']['id']
    record = await p._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{
        'id': 's1', 'durationSec': 5, 'action': '推门进入', 'characterIds': [],
    }]}
    await p._repository.save(record)
    events = []
    fail = {'poll': True}

    def handler(request):
        if request.method == 'POST':
            events.append('submit')
            return httpx.Response(200, json={'task_id': 'known-1'})
        if '/query/' in request.url.path:
            events.append('query')
            if fail['poll']:
                raise httpx.ReadTimeout('offline', request=request)
            return httpx.Response(200, json={'task': {'status': 'succeeded',
                'content': {'url': 'https://offline.invalid/video.mp4'}}})
        events.append('download')
        return httpx.Response(200, content=b'fake-video')

    p.set_video_provider(MinimaxH3Provider(api_key='offline-secret', prompt_mode='context-ir',
                                         transport=httpx.MockTransport(handler)))
    return runtime, pid, record.project['version'], events, fail


async def test_queue_is_read_only_and_recovery_never_submits_twice(video):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='click-1')
    assert job['status'] == 'queued' and events == []
    failed = await p.run_video_job(job['id'])
    assert failed['status'] == 'recoverable'
    assert failed['taskId'] == 'known-1'
    assert events == ['submit', 'query']
    fail['poll'] = False
    await p.recover_video_job(pid, job['id'])
    finished = await p.run_video_job(job['id'])
    assert finished['status'] == 'succeeded'
    assert events == ['submit', 'query', 'query', 'download']
    assert len((await p.get_snapshot(pid))['visualAssets']) == 1
    assert 'offline-secret' not in json.dumps(await p.list_video_jobs(pid))


async def test_duplicate_clicks_share_active_job(video):
    runtime, pid, version, events, _ = video
    results = await asyncio.gather(*[
        runtime.pipeline.request_video_job(pid, 's1', expected_version=version,
                                            operation_id=f'click-{i}') for i in range(5)])
    assert len({j['id'] for j in results}) == 1
    assert events == []


async def test_completed_video_waits_for_explicit_adoption(video):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='adopt-me')

    completed = await p.run_video_job(job['id'])
    assert completed['status'] == 'succeeded'
    assert completed['result']['adopted'] is False
    snapshot = await p.get_snapshot(pid)
    assert snapshot['visualAssets'][0]['valid'] is False
    assert snapshot['visualAssets'][0]['status'] == 'candidate'

    adopted = await p.adopt_video_job(pid, job['id'])
    assert adopted['result']['adopted'] is True
    snapshot = await p.get_snapshot(pid)
    assert snapshot['visualAssets'][0]['valid'] is True
    assert events == ['submit', 'query', 'download']


async def test_candidate_adoption_is_idempotent(video):
    runtime, pid, version, _, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='adopt-twice')
    completed = await p.run_video_job(job['id'])

    first = await p.adopt_video_job(pid, job['id'])
    second = await p.adopt_video_job(pid, job['id'])

    assert first['result']['adopted'] is True
    assert second['result']['adopted'] is True
    assert first['result']['assetId'] == completed['result']['assetId']
    assert len([asset for asset in (await p.get_snapshot(pid))['visualAssets']
                if asset.get('valid')]) == 1


async def test_candidate_adoption_rechecks_current_preflight(video):
    runtime, pid, version, _, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    job = await p.request_video_job(pid, 's1', expected_version=version,
                                    operation_id='stale-candidate')
    await p.run_video_job(job['id'])

    record = await p._repository.get(pid)
    record.project['script']['shots'][0]['action'] = '走进车厢'
    await p._repository.save(record)

    with pytest.raises(DomainError, match='VIDEO_JOB_CANDIDATE_STALE'):
        await p.adopt_video_job(pid, job['id'])
    snapshot = await p.get_snapshot(pid)
    assert snapshot['visualAssets'][0]['status'] == 'candidate'
    assert snapshot['visualAssets'][0]['valid'] is False


async def test_sql_adoption_fences_edits_and_invalidates_only_dependencies(sql_video, monkeypatch):
    (runtime, pid, version, events, fail), _ = sql_video
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project.update(visualAssets=[
        {'id': 'old', 'shotId': 's1', 'valid': True},
        {'id': 'dependent', 'shotId': 's2', 'cascadeFromShotId': 's1', 'valid': True},
        {'id': 'unrelated', 'shotId': 's3', 'valid': True},
    ], audioAssets=[{'shotId': 's1', 'source': 'video-native', 'valid': True}],
        timelines={'s1': {}, 's2': {}, 's3': {}}, exportManifest={'files': ['video.mp4']})
    await p._repository.save(record)
    fail['poll'] = False
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='atomic')
    await p.run_video_job(job['id'])
    before = (await p._repository.get(pid)).project
    assert before['visualAssets'][0]['valid'] and before['exportManifest']
    store = p._video_job_store
    original = store.adopt

    async def edit_before_commit(*args):
        changed = await p._repository.get(pid)
        changed.project['script']['shots'][0]['action'] = '输入已修改'
        await p._repository.save(changed)
        return await original(*args)

    monkeypatch.setattr(store, 'adopt', edit_before_commit)
    with pytest.raises(DomainError, match='VIDEO_JOB_CANDIDATE_STALE'):
        await p.adopt_video_job(pid, job['id'])
    assert not (await store.get(job['id']))['result']['asset']['valid']
    record = await p._repository.get(pid)
    record.project = before
    await p._repository.save(record)
    monkeypatch.setattr(store, 'adopt', original)
    assert (await p.adopt_video_job(pid, job['id']))['result']['adopted']
    after = (await p._repository.get(pid)).project
    assert [a['valid'] for a in after['visualAssets']] == [False, False, True, True]
    assert not after['audioAssets'][0]['valid']
    assert after['timelines'] == {'s3': {}} and after['exportManifest'] is None
    assert (await p.adopt_video_job(pid, job['id']))['result']['adopted']
    assert events == ['submit', 'query', 'download']


async def test_adoption_uses_selected_model_binding(video, monkeypatch):
    from comicflow.api.app import create_app
    runtime, pid, version, _, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='bound')
    await p.run_video_job(job['id'])
    seen = []

    async def select(base):
        seen.append(True)
        return base

    monkeypatch.setattr('comicflow.api.app.selected_runtime', select)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        response = await client.post(f'/api/projects/{pid}/video-jobs/{job["id"]}/adopt')
    assert response.status_code == 200 and seen == [True]


@pytest.fixture
async def sql_video(video, tmp_path):
    runtime, pid, version, events, fail = video
    engine, sessions = create_session_factory(f'sqlite+aiosqlite:///{tmp_path / "jobs.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    p = runtime.pipeline
    record = await p._repository.get(pid)
    p._repository = SqlAlchemyProjectRepository(sessions)
    await p._repository.save(record)
    p._video_job_store = SqlVideoJobStore(sessions)
    try:
        yield video, sessions
    finally:
        await engine.dispose()


async def test_sql_concurrent_enqueue_claim_and_lease_fencing(sql_video):
    (runtime, pid, version, events, _), sessions = sql_video
    p = runtime.pipeline
    jobs = await asyncio.gather(*[
        p.request_video_job(pid, 's1', expected_version=version, operation_id=f'op-{i}')
        for i in range(4)])
    assert len({job['id'] for job in jobs}) == 1
    assert len(await p._repository.pending_outbox()) == 1
    stores = [SqlVideoJobStore(sessions), SqlVideoJobStore(sessions)]
    claims = await asyncio.gather(*[
        store.claim(jobs[0]['id'], f'token-{i}') for i, store in enumerate(stores)])
    assert sum(claim is not None for claim in claims) == 1
    job = next(claim for claim in claims if claim)
    await stores[0].change(job['id'], lambda j: j.update(leaseUntil=0))
    assert await stores[1].claim(job['id'], 'replacement')
    with pytest.raises(DomainError, match='VIDEO_JOB_LEASE_LOST'):
        await stores[0].checkpoint(job['id'], job['leaseToken'], 'submitting')
    assert events == []


async def test_restart_uses_persisted_task_and_atomic_outbox(sql_video):
    (runtime, pid, version, events, fail), sessions = sql_video
    p = runtime.pipeline
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    assert (await p.run_video_job(job['id']))['status'] == 'recoverable'
    p._video_job_store = SqlVideoJobStore(sessions)
    assert (await p.list_video_jobs(pid))[0]['taskId'] == 'known-1'
    await p.recover_video_job(pid, job['id'])
    assert len(await p._repository.pending_outbox()) == 2
    fail['poll'] = False
    assert (await p.run_video_job(job['id']))['status'] == 'succeeded'
    assert events.count('submit') == 1
    assert len((await p.get_snapshot(pid))['visualAssets']) == 1
    assert (await p.run_video_job(job['id']))['status'] == 'succeeded'
    assert events.count('download') == 1


async def test_lost_submit_response_blocks_new_calls_and_allows_linking(video):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    original = p._dynamic_visual_provider._transport

    def lost(request):
        events.append('submit-lost')
        raise httpx.ReadTimeout('offline', request=request)

    p._dynamic_visual_provider._transport = httpx.MockTransport(lost)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    unknown = await p.run_video_job(job['id'])
    assert unknown['status'] == 'unknown' and unknown['canLinkTask']
    assert not unknown['canRecover']
    assert (await p.request_video_job(pid, 's1', expected_version=version,
                                     operation_id='another'))['id'] == job['id']
    with pytest.raises(DomainError, match='VIDEO_SUBMISSION_UNKNOWN'):
        await p.recover_video_job(pid, job['id'])
    assert (await p.run_video_job(job['id']))['status'] == 'unknown'
    p._dynamic_visual_provider._transport = original
    fail['poll'] = False
    await p.recover_video_job(pid, job['id'], 'known-1')
    assert (await p.run_video_job(job['id']))['status'] == 'succeeded'
    assert events == ['submit-lost', 'query', 'download']


async def test_task_id_checkpoint_failure_does_not_repeat_submission(video, monkeypatch):
    runtime, pid, version, events, _ = video
    p = runtime.pipeline
    store = p._video_job_store
    original = store.checkpoint

    async def broken(job_id, token, status, fields=None):
        if status == 'polling':
            raise RuntimeError('database offline')
        return await original(job_id, token, status, fields)

    monkeypatch.setattr(store, 'checkpoint', broken)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    assert (await p.run_video_job(job['id']))['status'] == 'unknown'
    assert events == ['submit']
    assert (await p.run_video_job(job['id']))['status'] == 'unknown'
    assert events == ['submit']


async def test_task_id_is_committed_before_poll_and_crash_can_resume(sql_video):
    (runtime, pid, version, events, fail), sessions = sql_video
    p = runtime.pipeline
    original = p._dynamic_visual_provider._transport
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')

    class Crash(BaseException):
        pass

    async def crash(request):
        if '/query/' in request.url.path:
            saved = await SqlVideoJobStore(sessions).get(job['id'])
            assert saved['taskId'] == 'known-1'
            raise Crash()
        return await original.handle_async_request(request)

    p._dynamic_visual_provider._transport = httpx.MockTransport(crash)
    with pytest.raises(Crash):
        await p.run_video_job(job['id'])
    await p._video_job_store.change(job['id'], lambda j: j.update(leaseUntil=0))
    p._dynamic_visual_provider._transport = original
    fail['poll'] = False
    await p.recover_video_job(pid, job['id'])
    assert (await p.run_video_job(job['id']))['status'] == 'succeeded'
    assert events.count('submit') == 1


@pytest.mark.parametrize('deleted', [False, True])
async def test_input_change_keeps_result_candidate_and_old_video(sql_video, deleted):
    (runtime, pid, version, _, fail), _sessions = sql_video
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['visualAssets'] = [{'id': 'old', 'shotId': 's1', 'valid': True}]
    await p._repository.save(record)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    await p.run_video_job(job['id'])
    record = await p._repository.get(pid)
    if deleted:
        record.project['script']['shots'] = []
    else:
        record.project['script']['shots'][0]['action'] = '走向窗边'
    await p._repository.save(record)
    fail['poll'] = False
    await p.recover_video_job(pid, job['id'])
    done = await p.run_video_job(job['id'])
    assert done['status'] == 'succeeded' and not done['result']['adopted']
    assets = (await p.get_snapshot(pid))['visualAssets']
    assert assets[0]['valid'] and assets[1]['status'] == 'candidate'


async def test_operation_replay_survives_input_changes(video):
    runtime, pid, version, events, _ = video
    p = runtime.pipeline
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    record = await p._repository.get(pid)
    record.project['version'] += 1
    await p._repository.save(record)
    assert (await p.request_video_job(pid, 's1', expected_version=version,
                                     operation_id='one'))['id'] == job['id']
    with pytest.raises(DomainError, match='VIDEO_JOB_ACTIVE'):
        await p.request_video_job(pid, 's1', expected_version=version + 1, operation_id='two')
    assert events == []


async def test_config_change_does_not_send_to_new_endpoint(video):
    runtime, pid, version, events, _ = video
    p = runtime.pipeline
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    await p.run_video_job(job['id'])
    p._dynamic_visual_provider._base_url = 'https://other.invalid'
    await p.recover_video_job(pid, job['id'])
    stopped = await p.run_video_job(job['id'])
    assert stopped['status'] == 'recoverable'
    assert stopped['error'] == 'VIDEO_JOB_CONFIG_CHANGED'
    assert events == ['submit', 'query']


async def test_job_api_permissions_queue_only_and_independent_read(video, monkeypatch):
    from comicflow.api.app import create_app
    runtime, pid, version, events, _ = video
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['ownerUserId'] = 'owner'
    await p._repository.save(record)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        path = f'/api/projects/{pid}/shots/s1/video-jobs'
        data = {'expectedVersion': version, 'operationId': 'one'}
        assert (await client.post(path, json=data)).status_code == 403
        created = await client.post(path, json=data, headers={'X-User-Id': 'owner'})
        assert created.status_code == 202
        assert events == []
        job_id = created.json()['id']

        async def invalid_current(*args):
            raise DomainError('PROVIDER_NOT_CONFIGURED')

        monkeypatch.setattr('comicflow.api.app.selected_runtime', invalid_current)
        path = f'/api/projects/{pid}/video-jobs'
        assert (await client.get(path)).status_code == 403
        response = await client.get(path, headers={'X-User-Id': 'owner'})
        assert response.status_code == 200 and response.json()['items'][0]['id'] == job_id
        assert 'configSignature' not in response.text and 'offline-secret' not in response.text
        response = await client.post(f'{path}/{job_id}/recover', json={},
                                     headers={'X-User-Id': 'owner'})
        assert response.status_code == 202 and events == []


async def test_saved_text_expansion_is_reused_after_crash(video, monkeypatch):
    from comicflow.providers.h3_skill import H3SkillPromptWriter
    from test_h3_skill_execution import valid_rewrite

    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    text_calls = []

    async def rewrite(system, user):
        text_calls.append(user)
        return await valid_rewrite(system, user)

    p._dynamic_visual_provider._prompt_mode = 'local-skill'
    p._dynamic_visual_provider.set_prompt_writer(H3SkillPromptWriter(rewrite))
    store = p._video_job_store
    original = store.checkpoint

    class Crash(BaseException):
        pass

    async def crash(job_id, token, status, fields=None):
        if status == 'submitting':
            raise Crash()
        return await original(job_id, token, status, fields)

    monkeypatch.setattr(store, 'checkpoint', crash)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    with pytest.raises(Crash):
        await p.run_video_job(job['id'])
    assert len(text_calls) == 1 and events == []
    saved = await store.get(job['id'])
    assert saved['status'] == 'prepared' and saved['compiled']['prompt']
    monkeypatch.setattr(store, 'checkpoint', original)
    await store.change(job['id'], lambda j: j.update(leaseUntil=0))
    fail['poll'] = False
    await p.recover_video_job(pid, job['id'])
    assert (await p.run_video_job(job['id']))['status'] == 'succeeded'
    assert len(text_calls) == 1 and events.count('submit') == 1


async def test_rules_change_while_queued_stops_before_models(video, monkeypatch):
    runtime, pid, version, events, _ = video
    p = runtime.pipeline
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    original = p._dynamic_visual_provider.prepare_preview

    def changed(*args):
        result = original(*args)
        result['prompt']['text'] += 'changed rules'
        return result

    monkeypatch.setattr(p._dynamic_visual_provider, 'prepare_preview', changed)
    failed = await p.run_video_job(job['id'])
    assert failed['status'] == 'failed' and failed['error'] == 'VIDEO_JOB_CONFIG_CHANGED'
    assert events == []


@pytest.mark.parametrize('phase', ['download', 'finish'])
async def test_recover_download_or_finalization_never_regenerates(video, monkeypatch, phase):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    store = p._video_job_store
    original_finish = store.finish
    original_transport = p._dynamic_visual_provider._transport

    async def broken_finish(*args):
        raise RuntimeError('storage failed with private data')

    async def broken_download(request):
        if request.url.host == 'offline.invalid':
            return httpx.Response(503)
        return await original_transport.handle_async_request(request)

    if phase == 'finish':
        monkeypatch.setattr(store, 'finish', broken_finish)
    else:
        p._dynamic_visual_provider._transport = httpx.MockTransport(broken_download)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    result = await p.run_video_job(job['id'])
    assert result['status'] == 'recoverable'
    assert 'private data' not in json.dumps(result)
    monkeypatch.setattr(store, 'finish', original_finish)
    p._dynamic_visual_provider._transport = original_transport
    await p.recover_video_job(pid, job['id'])
    result = await p.run_video_job(job['id'])
    assert result['status'] == 'succeeded' and events.count('submit') == 1
    assert events.count('download') == 1


@pytest.mark.parametrize('terminal', [False, True])
async def test_wan_recovers_query_without_resubmitting(video, terminal):
    from comicflow.providers.bailian_i2v import BailianImageToVideoProvider

    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    record = await p._repository.get(pid)
    record.project['script']['shots'][0]['visualDescription'] = '雨夜推门'
    await p._repository.save(record)

    def handler(request):
        if request.method == 'POST':
            events.append('submit')
            return httpx.Response(200, json={'output': {'task_id': 'wan-1'}})
        if '/tasks/' in request.url.path:
            events.append('query')
            if fail['poll']:
                raise httpx.ReadTimeout('offline', request=request)
            return httpx.Response(200, json={'output': {
                'task_status': 'FAILED' if terminal else 'SUCCEEDED',
                'video_url': 'https://offline.invalid/video.mp4',
            }})
        events.append('download')
        return httpx.Response(200, content=b'video')

    p.set_video_provider(BailianImageToVideoProvider(api_key='offline', model='wan2.7-t2v',
        generation_type='t2v', resolution='720P', transport=httpx.MockTransport(handler)))
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    assert (await p.run_video_job(job['id']))['status'] == 'recoverable'
    fail['poll'] = False
    await p.recover_video_job(pid, job['id'])
    assert (await p.run_video_job(job['id']))['status'] == ('failed' if terminal else 'succeeded')
    assert events.count('submit') == 1


async def test_worker_resolves_original_registry_revision(video, monkeypatch):
    from comicflow.providers.model_selection import selected_runtime
    from comicflow.worker.tasks import execute_video_job

    runtime, pid, version, events, fail = video
    registry = runtime.model_registry
    view = await registry.mutate('connection', None, {'revision': 0, 'name': 'old',
        'baseUrl': 'https://old.invalid', 'apiKey': 'old-private-key'})
    connection = view['connections'][0]['id']
    view = await registry.mutate('model', None, {'revision': view['revision'], 'name': 'H3',
        'connectionId': connection, 'protocol': 'compshare-h3', 'model': 'MiniMax-H3',
        'enabled': True, 'config': {'h3PromptMode': 'context-ir'}})
    view = await registry.bind({'revision': view['revision'],
                                'bindings': {'video': view['models'][0]['id']}})
    selected = await selected_runtime(runtime)
    job = await selected.pipeline.request_video_job(pid, 's1', expected_version=version,
                                                    operation_id='one')
    old_revision = view['revision']
    await registry.mutate('connection', connection, {'revision': old_revision, 'name': 'new',
        'baseUrl': 'https://new.invalid', 'apiKey': 'new-private-key'})
    transport = runtime.pipeline._dynamic_visual_provider._transport
    seen = []

    async def resolve(base, revision):
        restored = await selected_runtime(base, revision)
        provider = restored.pipeline._dynamic_visual_provider
        seen.append((revision, provider._base_url, provider._api_key))
        provider._transport = transport
        return restored

    monkeypatch.setattr('comicflow.worker.tasks.selected_runtime', resolve)
    fail['poll'] = False
    assert (await execute_video_job(runtime, job['id']))['status'] == 'succeeded'
    assert seen == [(old_revision, 'https://old.invalid', 'old-private-key')]
    assert events.count('submit') == 1


async def test_create_rolls_back_job_when_outbox_cannot_be_saved(sql_video, monkeypatch):
    from comicflow.infrastructure.database import VideoJobRow
    from sqlalchemy import func, select

    (runtime, pid, version, _, _), sessions = sql_video

    def fail(*args):
        raise RuntimeError('outbox unavailable')

    monkeypatch.setattr(runtime.pipeline._video_job_store, 'enqueue', fail)
    with pytest.raises(RuntimeError, match='outbox unavailable'):
        await runtime.pipeline.request_video_job(pid, 's1', expected_version=version,
                                                 operation_id='one')
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(VideoJobRow)) == 0
    assert await runtime.pipeline._repository.pending_outbox() == []


async def test_migration_builds_video_journal_on_temporary_database(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    url = f'sqlite+aiosqlite:///{tmp_path / "migration.db"}'
    monkeypatch.setenv('DATABASE_URL', url)
    await asyncio.to_thread(command.upgrade, Config('alembic.ini'), 'head')
    engine, _ = create_session_factory(url)
    try:
        async with engine.connect() as connection:
            constraints = await connection.run_sync(
                lambda conn: inspect(conn).get_unique_constraints('video_generation_jobs'))
            assert {tuple(c['column_names']) for c in constraints} == {
                ('active_slot',), ('operation_key',)}
    finally:
        await engine.dispose()


async def test_legacy_automatic_replay_cannot_resubmit_unknown_job(video):
    runtime, pid, version, events, _ = video
    p = runtime.pipeline

    def timeout(request):
        events.append('submit')
        raise httpx.ReadTimeout('offline', request=request)

    p._dynamic_visual_provider._transport = httpx.MockTransport(timeout)
    for _ in range(2):
        with pytest.raises(DomainError, match='PROVIDER_TIMEOUT'):
            await p.generate_shot_visual(pid, 's1', expected_version=version)
    assert events == ['submit']
    assert (await p.list_video_jobs(pid))[0]['status'] == 'unknown'


async def test_candidate_cannot_advance_legacy_automatic_flow(video):
    runtime, pid, version, _, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    original = p._dynamic_visual_provider._transport

    async def edit_during_generation(request):
        if request.method == 'POST':
            record = await p._repository.get(pid)
            record.project['script']['shots'][0]['action'] = '走向窗边'
            await p._repository.save(record)
        return await original.handle_async_request(request)

    p._dynamic_visual_provider._transport = httpx.MockTransport(edit_during_generation)
    result = await p.generate_shot_visual(pid, 's1', expected_version=version)
    assert result['awaitingAdoption'] is True
    with pytest.raises(DomainError, match='VIDEO_JOB_CANDIDATE_STALE'):
        await p.adopt_video_job(pid, result['jobId'])
    assert len((await p.get_snapshot(pid))['visualAssets']) == 1


async def test_unavailable_journal_returns_safe_503(video, monkeypatch):
    from comicflow.api.app import create_app
    from sqlalchemy.exc import SQLAlchemyError

    runtime, pid, _, _, _ = video

    async def broken(*args):
        raise SQLAlchemyError('private database credentials')

    monkeypatch.setattr(runtime.pipeline._video_job_store, 'list', broken)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        response = await client.get(f'/api/projects/{pid}/video-jobs')
        assert response.status_code == 503
        assert response.json() == {'error': 'VIDEO_JOB_STORAGE_UNAVAILABLE'}


async def test_unknown_text_call_is_not_repeated(video):
    from comicflow.providers.h3_skill import H3SkillPromptWriter

    runtime, pid, version, events, _ = video
    p = runtime.pipeline
    text_calls = []

    async def timeout(*args):
        text_calls.append(1)
        raise RuntimeError('PROVIDER_TIMEOUT')

    p._dynamic_visual_provider._prompt_mode = 'local-skill'
    p._dynamic_visual_provider.set_prompt_writer(H3SkillPromptWriter(timeout))
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    result = await p.run_video_job(job['id'])
    assert result['status'] == 'unknown' and not result['canLinkTask']
    assert result['callsStarted'] == {'text': 1, 'video': 0}
    assert (await p.run_video_job(job['id']))['status'] == 'unknown'
    assert text_calls == [1] and events == []


async def test_stale_project_write_cannot_erase_a_completed_video(sql_video):
    (runtime, pid, version, _, fail), _ = sql_video
    p = runtime.pipeline
    stale = await p._repository.get(pid)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='one')
    fail['poll'] = False
    assert (await p.run_video_job(job['id']))['status'] == 'succeeded'
    stale.project['title'] = 'late editor'
    with pytest.raises(DomainError, match='VERSION_CONFLICT'):
        await p._repository.save(stale)
    assert len((await p.get_snapshot(pid))['visualAssets']) == 1

@pytest.mark.parametrize('entry', ['sync', 'visual', 'shot'])
async def test_legacy_entries_return_candidate_without_audio_or_replacement(
    video, monkeypatch, entry,
):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    record = await p._repository.get(pid)
    record.project['visualAssets'] = [{'id': 'original', 'shotId': 's1', 'valid': True}]
    await p._repository.save(record)

    async def forbidden(*args, **kwargs):
        pytest.fail('candidate must not start audio')

    monkeypatch.setattr(p, 'generate_shot_audio', forbidden)
    if entry == 'sync':
        result = await p.generate_shot_visual(pid, 's1', expected_version=version)
    else:
        result = await p.regenerate_shot(pid, 's1', scope=entry, expected_version=version)
    assert result['awaitingAdoption'] is True
    assert result['jobId']
    assert not result['asset']['valid']
    assert (await p.get_snapshot(pid))['visualAssets'][0]['valid']
    assert events.count('submit') == 1
    replay = await p.generate_shot_visual(pid, 's1', expected_version=version)
    assert replay['jobId'] == result['jobId']
    assert events.count('submit') == 1


async def test_automatic_pauses_on_candidate_and_only_explicit_resume_can_continue(video):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    record = await p._repository.get(pid)
    record.project.update(stage='storyboard-ready', generationSession={
        'mode': 'automatic', 'status': 'ready', 'stage': 'storyboard-ready'})
    record.project['input']['mode'] = 'automatic'
    record.project['script']['shots'].append({
        'id': 's2', 'durationSec': 5, 'characterIds': [], 'action': '抬头', 'sceneId': 'new'})
    await p._repository.save(record)
    session = await p.advance_generation_session(pid)
    assert session['status'] == 'paused'
    assert session['pauseReason'] == 'video-awaiting-adoption'
    assert session['lastError'] is None
    assert session['waitingJobId']
    assert events.count('submit') == 1
    assert (await p.advance_generation_session(pid))['status'] == 'paused'
    with pytest.raises(DomainError, match='VIDEO_JOB_AWAITING_ADOPTION'):
        await p.update_generation_session(pid, 'resume')
    await p.adopt_video_job(pid, session['waitingJobId'])
    assert (await p.advance_generation_session(pid))['status'] == 'paused'
    assert events.count('submit') == 1
    resumed = await p.update_generation_session(pid, 'resume')
    assert resumed['status'] == 'ready' and not resumed.get('waitingJobId')
    next_session = await p.advance_generation_session(pid)
    assert next_session['status'] == 'paused'
    assert next_session['waitingShotId'] == 's2'
    assert events.count('submit') == 2


@pytest.mark.parametrize('stage', ['storyboard-ready', 'visual-completed', 'audio-completed'])
async def test_automatic_finds_candidate_from_other_entry_without_new_submission(video, stage):
    runtime, pid, version, events, fail = video
    p = runtime.pipeline
    fail['poll'] = False
    record = await p._repository.get(pid)
    record.project.update(stage=stage, generationSession={'mode': 'automatic', 'status': 'ready'})
    await p._repository.save(record)
    job = await p.request_video_job(pid, 's1', expected_version=version, operation_id='page')
    await p.run_video_job(job['id'])
    result = await p.advance_generation_session(pid)
    assert result['status'] == 'paused' and result['waitingJobId'] == job['id']
    assert events.count('submit') == 1
    await p.adopt_video_job(pid, job['id'])
    resumed = await p.update_generation_session(pid, 'resume')
    assert resumed['stage'] == 'storyboard-ready'
    assert events.count('submit') == 1
    # Recheck affected visuals before audio/composition; adoption may invalidate a tail dependency.
    assert (await p.advance_generation_session(pid))['stage'] == 'visual-completed'


async def test_mock_legacy_entry_also_requires_adoption():
    p = create_memory_runtime().pipeline
    created = await p.create_project(CreateProject(
        input_type='story', story='暴雨夜女子走进便利店寻找朋友。',
        duration_sec=30, mode='import_story'))
    pid = created['project']['id']
    record = await p._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [
        {'id': 's1', 'durationSec': 5, 'characterIds': []}]}
    await p._repository.save(record)
    result = await p.generate_shot_visual(pid, 's1', expected_version=record.project['version'])
    assert result['awaitingAdoption'] and not result['asset']['valid']
    await p.adopt_video_job(pid, result['jobId'])
    assert (await p.get_snapshot(pid))['visualAssets'][0]['valid']
