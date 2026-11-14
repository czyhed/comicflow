"""No paid requests: journal behaviour with controlled image providers."""

import asyncio
import io
import json
from copy import deepcopy

import httpx
import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.database import (
    Base,
    SqlAlchemyCharacterRepository,
    SqlAlchemyProjectRepository,
    create_session_factory,
)
from comicflow.infrastructure.image_jobs import SqlImageJobStore
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.wanx_image import BailianImageProvider
from PIL import Image


@pytest.fixture
async def images():
    p = create_memory_runtime().pipeline
    created = await p.create_project(
        CreateProject(
            input_type="story",
            story="小雨在雨夜等候最后一班公交车，准备回家。",
            duration_sec=30,
            mode="import_story",
        )
    )
    pid = created["project"]["id"]
    card = await p.save_project_character(
        pid,
        dict(
            name="小雨",
            appearance="黑色短发",
            clothing="蓝色外套",
            personality="沉静",
            voice={"language": "zh-CN"},
        ),
    )
    content = io.BytesIO()
    Image.new("RGB", (256, 384), "navy").save(content, "PNG")
    calls, objects, control = [], {}, {"poll_error": False, "submit_error": False}

    class Store:
        async def put_bytes(self, object_key, content, content_type):
            objects[object_key] = content

        async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
            return objects[key]

        async def presigned_get_url(self, key, expires_in=900):
            return f"https://offline.invalid/{key}"

    def handler(request):
        if request.method == "POST":
            calls.append("submit")
            if control.get("submit_exception"):
                raise control["submit_exception"]("sensitive transport detail", request=request)
            if control.get("submit_response"):
                status, body = control["submit_response"]
                return httpx.Response(status, json=body)
            if control["submit_error"]:
                raise httpx.ReadTimeout("offline", request=request)
            return httpx.Response(
                200, json={"output": {"task_id": f"task-{calls.count('submit')}"}}
            )
        if "/tasks/" in request.url.path:
            calls.append("poll")
            if control["poll_error"]:
                raise httpx.ReadTimeout("offline", request=request)
            return httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [{"url": "https://offline.invalid/result.png"}],
                        "choices": [
                            {
                                "message": {
                                    "content": [{"image": "https://offline.invalid/result.png"}]
                                }
                            }
                        ],
                    }
                },
            )
        calls.append("download")
        return httpx.Response(200, content=content.getvalue())

    p._asset_store = Store()
    p.set_reference_image_provider(
        BailianImageProvider(
            api_key="test-only-secret",
            transport=httpx.MockTransport(handler),
            asset_store=p._asset_store,
        )
    )
    version = (await p.get_snapshot(pid))["project"]["version"]
    return p, pid, card, version, calls, control


async def request(images, operation="one", purpose="candidate"):
    p, pid, card, version, *_ = images
    return await p.request_image_job(
        pid, card["id"], expected_version=version, operation_id=operation, purpose=purpose
    )


async def test_duplicate_clicks_and_workers_submit_only_once(images):
    p, pid, card, _, calls, _ = images
    jobs = await asyncio.gather(*(request(images, str(i)) for i in range(5)))
    assert len({j["id"] for j in jobs}) == 1 and not calls
    await asyncio.gather(*(p.run_image_job(jobs[0]["id"]) for _ in range(3)))
    job = await p.get_image_job(pid, jobs[0]["id"])
    assert job["status"] == "succeeded" and calls.count("submit") == 1
    saved = await p._character_repository.get(card["id"])
    assert saved["referenceImageCandidate"]["mediaType"] == "image"
    assert not saved.get("referenceImageObjectKey")
    assert "test-only-secret" not in json.dumps(await p.list_image_jobs(pid))


@pytest.mark.parametrize(
    "transport_error", [httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError],
)
async def test_image_transport_failure_preserves_safe_diagnostics_without_resubmitting(
    images, transport_error,
):
    p, pid, _, _, calls, control = images
    control['submit_exception'] = transport_error
    job = await request(images)
    await p.run_image_job(job['id'])
    public = await p.get_image_job(pid, job['id'])
    assert public['status'] == 'unknown'
    assert public['errorDetail'] == {
        'stage': 'submitting', 'transportError': transport_error.__name__,
    }
    assert 'sensitive transport detail' not in json.dumps(public)
    assert (await request(images, 'another'))['id'] == job['id']
    await p.run_image_job(job['id'])
    assert calls == ['submit']


@pytest.mark.parametrize(
    'status,code,job_status',
    [(502, 'InternalError', 'unknown'), (400, 'InvalidParameter', 'failed')],
)
async def test_image_http_failure_preserves_status_and_request_id_without_raw_response(
    images, status, code, job_status,
):
    p, pid, _, _, calls, control = images
    control['submit_response'] = (status, {
        'code': code, 'message': 'secret prompt and credentials must not be returned',
        'request_id': 'a4d6bc3e-7890-4321-aaaa-bbbbccccdddd',
    })
    job = await request(images)
    await p.run_image_job(job['id'])
    public = await p.get_image_job(pid, job['id'])
    assert public['status'] == job_status
    assert public['errorDetail'] == {
        'stage': 'submitting', 'upstreamStatus': status, 'upstreamCode': code,
        'requestId': 'a4d6bc3e-7890-4321-aaaa-bbbbccccdddd',
    }
    assert 'secret prompt' not in json.dumps(public)
    assert calls == ['submit']


async def test_known_task_recovers_without_resubmission(images):
    p, pid, _, _, calls, control = images
    control["poll_error"] = True
    job = await request(images)
    result = await p.run_image_job(job["id"])
    assert result["status"] == "recoverable" and result["taskId"] == "task-1"
    control["poll_error"] = False
    await p.recover_image_job(pid, job["id"])
    result = await p.run_image_job(job["id"])
    assert result["status"] == "succeeded" and calls.count("submit") == 1


async def test_unknown_submission_stays_blocked_even_with_new_operation(images):
    p, pid, _, _, calls, control = images
    control["submit_error"] = True
    job = await request(images)
    result = await p.run_image_job(job["id"])
    assert result["status"] == "unknown" and not result["canRecover"]
    assert (await request(images, "another"))["id"] == job["id"]
    with pytest.raises(DomainError, match="IMAGE_SUBMISSION_UNKNOWN"):
        await p.recover_image_job(pid, job["id"])
    await p.run_image_job(job["id"])
    assert calls == ["submit"]


async def test_changed_character_keeps_paid_result_without_installing(images):
    p, pid, card, _, calls, _ = images
    job = await request(images)
    changed = deepcopy(await p._character_repository.get(card["id"]))
    changed.update(appearance="白发", revision=1)
    await p._character_repository.save(changed)
    result = await p.run_image_job(job["id"])
    assert result["status"] == "failed" and result["error"] == "IMAGE_JOB_INPUT_CHANGED"
    assert calls == []


async def test_config_change_does_not_submit_on_another_model(images):
    p, _, _, _, calls, _ = images
    job = await request(images)
    p._reference_image_provider._model = "different-model"
    result = await p.run_image_job(job["id"])
    assert result["status"] == "failed" and result["error"] == "IMAGE_JOB_CONFIG_CHANGED"
    assert not calls


@pytest.fixture
async def sql_images(images, tmp_path):
    p, pid, card, *_ = images
    engine, sessions = create_session_factory(f"sqlite+aiosqlite:///{tmp_path / 'images.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    record = await p._repository.get(pid)
    p._repository = SqlAlchemyProjectRepository(sessions)
    await p._repository.save(record)
    p._character_repository = SqlAlchemyCharacterRepository(sessions)
    await p._character_repository.save(card)
    p._image_job_store = SqlImageJobStore(sessions)
    try:
        yield images, sessions
    finally:
        await engine.dispose()


async def test_sql_creation_outbox_and_lease_are_atomic(sql_images):
    images, sessions = sql_images
    p, _, _, _, calls, _ = images
    jobs = await asyncio.gather(*(request(images, f"op-{i}") for i in range(4)))
    assert len({j["id"] for j in jobs}) == 1
    outbox = await p._repository.pending_outbox()
    assert len(outbox) == 1 and outbox[0]["topic"] == "production.image.queued"
    stores = [SqlImageJobStore(sessions), SqlImageJobStore(sessions)]
    claims = await asyncio.gather(*(s.claim(jobs[0]["id"], str(i)) for i, s in enumerate(stores)))
    assert sum(c is not None for c in claims) == 1
    claimed = next(c for c in claims if c)
    await stores[0].change(claimed["id"], lambda j: j.update(leaseUntil=0))
    assert await stores[1].claim(claimed["id"], "new-owner")
    with pytest.raises(DomainError, match="IMAGE_JOB_LEASE_LOST"):
        await stores[0].checkpoint(claimed["id"], claimed["leaseToken"], "submitting")
    assert calls == []


async def test_task_id_survives_worker_crash_and_store_restart(sql_images):
    images, sessions = sql_images
    p, pid, _, _, calls, _ = images
    job = await request(images)
    original = p._reference_image_provider._transport

    class Crash(BaseException):
        pass

    async def crash(request):
        if "/tasks/" in request.url.path:
            assert (await SqlImageJobStore(sessions).get(job["id"]))["taskId"] == "task-1"
            raise Crash()
        return await original.handle_async_request(request)

    p._reference_image_provider._transport = httpx.MockTransport(crash)
    with pytest.raises(Crash):
        await p.run_image_job(job["id"])
    p._image_job_store = SqlImageJobStore(sessions)
    await p._image_job_store.change(job["id"], lambda j: j.update(leaseUntil=0))
    p._reference_image_provider._transport = original
    await p.recover_image_job(pid, job["id"])
    assert (await p.run_image_job(job["id"]))["status"] == "succeeded"
    assert calls.count("submit") == 1
    assert len(await p._repository.pending_outbox()) == 2


async def test_failed_task_id_checkpoint_blocks_new_submission(images, monkeypatch):
    p, _, _, _, calls, _ = images
    original = p._image_job_store.checkpoint

    async def broken(job_id, token, status, fields=None):
        if status == "polling":
            raise RuntimeError("database unavailable")
        return await original(job_id, token, status, fields)

    monkeypatch.setattr(p._image_job_store, "checkpoint", broken)
    job = await request(images)
    assert (await p.run_image_job(job["id"]))["status"] == "unknown"
    assert (await p.run_image_job(job["id"]))["status"] == "unknown"
    assert calls == ["submit"]


async def test_paid_result_after_edit_is_retained_and_never_overwrites_character(sql_images):
    images, _ = sql_images
    p, pid, card, _, calls, control = images
    control["poll_error"] = True
    job = await request(images)
    await p.run_image_job(job["id"])
    changed = await p._character_repository.get(card["id"])
    changed.update(clothing="白衬衫", revision=1)
    await p._character_repository.save(changed)
    control["poll_error"] = False
    await p.recover_image_job(pid, job["id"])
    done = await p.run_image_job(job["id"])
    assert done["status"] == "succeeded" and done["applied"] is False
    stored = await p._image_job_store.get(job["id"])
    assert stored["results"]["candidate"]["objectKey"]
    current = await p._character_repository.get(card["id"])
    assert current["clothing"] == "白衬衫" and not current.get("referenceImageCandidate")
    assert calls.count("submit") == 1


async def test_saved_image_finalization_recovers_without_provider_calls(images, monkeypatch):
    p, pid, _, _, calls, _ = images
    original = p._image_job_store.install

    async def broken(*args, **kwargs):
        raise RuntimeError("temporary storage failure")

    monkeypatch.setattr(p._image_job_store, "install", broken)
    job = await request(images)
    assert (await p.run_image_job(job["id"]))["status"] == "recoverable"
    before = calls[:]
    p._reference_image_provider._model = "no-longer-selected"
    monkeypatch.setattr(p._image_job_store, "install", original)
    await p.recover_image_job(pid, job["id"])
    assert (await p.run_image_job(job["id"]))["status"] == "succeeded"
    assert calls == before


async def test_partial_views_resume_only_missing_results(images):
    p, pid, card, version, calls, _ = images
    main = await p.generate_character_reference_candidate(pid, card["id"], expected_version=version)
    approved = await p.approve_character_reference_candidate(
        pid, card["id"], main["candidate"]["id"], expected_version=main["projectVersion"]
    )
    p._reference_image_provider._model = "wan2.6-image"
    original = p._reference_image_provider._transport
    fail = True

    async def partial(req):
        if fail and "/tasks/task-3" in req.url.path:
            raise httpx.ReadTimeout("offline", request=req)
        return await original.handle_async_request(req)

    p._reference_image_provider._transport = httpx.MockTransport(partial)
    job = await p.request_image_job(
        pid,
        card["id"],
        expected_version=approved["projectVersion"],
        operation_id="views",
        purpose="views",
    )
    failed = await p.run_image_job(job["id"])
    assert failed["status"] == "recoverable" and failed["completedSteps"] == ["front"], failed
    assert calls.count("submit") == 3
    fail = False
    await p.recover_image_job(pid, job["id"])
    done = await p.run_image_job(job["id"])
    assert done["status"] == "succeeded" and calls.count("submit") == 4
    character = await p._character_repository.get(card["id"])
    assert len(character["referenceViews"]) == 3 and character["referenceBoard"]["objectKey"]


async def test_sql_unknown_remains_blocking_after_restart(sql_images):
    images, sessions = sql_images
    p, _, _, _, calls, control = images
    control["submit_error"] = True
    job = await request(images)
    await p.run_image_job(job["id"])
    p._image_job_store = SqlImageJobStore(sessions)
    assert (await request(images, "new-click"))["id"] == job["id"]
    assert (await p.run_image_job(job["id"]))["status"] == "unknown"
    assert calls == ["submit"]


async def test_synchronous_response_loss_is_unknown(images):
    from comicflow.providers.openai_image import OpenAIImageProvider

    p, _, _, _, calls, _ = images

    def timeout(req):
        calls.append("sync-submit")
        raise httpx.ReadTimeout("offline", request=req)

    p.set_reference_image_provider(
        OpenAIImageProvider(
            api_key="offline",
            base_url="https://offline.invalid",
            model="sync-image",
            transport=httpx.MockTransport(timeout),
        )
    )
    job = await request(images)
    assert (await p.run_image_job(job["id"]))["status"] == "unknown"
    assert calls == ["sync-submit"]


async def test_image_http_returns_202_without_running_and_checks_project_access(images):
    from dataclasses import replace

    from comicflow.api.app import create_app

    p, pid, card, version, calls, _ = images
    runtime = replace(create_memory_runtime(), pipeline=p)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/api/projects/{pid}/characters/{card['id']}/image-jobs",
            json={"expectedVersion": version, "operationId": "http-click", "purpose": "candidate"},
        )
        assert response.status_code == 202 and not calls
        jid = response.json()["id"]
        assert (await client.get(f"/api/projects/{pid}/image-jobs/{jid}")).status_code == 200
        another = await p.create_project(
            CreateProject(
                input_type="story",
                story="另一个人在远处的车站等待末班公交车。",
                duration_sec=30,
                mode="import_story",
            )
        )
        other = another["project"]["id"]
        assert (await client.get(f"/api/projects/{other}/image-jobs/{jid}")).status_code == 404
        assert (
            await client.post(f"/api/projects/{other}/image-jobs/{jid}/recover")
        ).status_code == 404
        assert not calls


async def test_known_terminal_failure_does_not_offer_poll_recovery(images):
    p, _, _, _, _, _ = images

    def rejected(req):
        if req.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "rejected-task"}})
        return httpx.Response(
            200, json={"output": {"task_status": "FAILED", "code": "DataInspectionFailed"}}
        )

    p._reference_image_provider._transport = httpx.MockTransport(rejected)
    job = await request(images)
    done = await p.run_image_job(job["id"])
    assert done["status"] == "failed" and not done["canRecover"]
    assert done["error"] == "IMAGE_CONTENT_REJECTED"


async def test_stale_character_save_cannot_erase_installed_candidate(sql_images):
    images, _ = sql_images
    p, _, card, _, _, _ = images
    stale = await p._character_repository.get(card["id"])
    job = await request(images)
    assert (await p.run_image_job(job["id"]))["status"] == "succeeded"
    edited = {**stale, "clothing": "白衣", "revision": 1}
    with pytest.raises(DomainError, match="CHARACTER_VERSION_CONFLICT"):
        await p._character_repository.save(edited, expected=stale)
    assert (await p._character_repository.get(card["id"]))["referenceImageCandidate"]


async def test_temporary_migration_creates_unique_image_slots(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    url = f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    await asyncio.to_thread(command.upgrade, Config("alembic.ini"), "head")
    engine, _ = create_session_factory(url)
    try:
        async with engine.connect() as connection:
            constraints = await connection.run_sync(
                lambda conn: inspect(conn).get_unique_constraints("image_generation_jobs")
            )
            assert {tuple(c["column_names"]) for c in constraints} == {
                ("active_slot",),
                ("operation_key",),
            }
    finally:
        await engine.dispose()


async def test_board_storage_failure_retries_composition_only(images, monkeypatch):
    from comicflow.production.character_assets import CharacterAssets

    p, pid, card, version, calls, _ = images
    main = await p.generate_character_reference_candidate(pid, card["id"], expected_version=version)
    approved = await p.approve_character_reference_candidate(
        pid, card["id"], main["candidate"]["id"], expected_version=main["projectVersion"]
    )
    p._reference_image_provider._model = "wan2.6-image"
    original = CharacterAssets._compose_character_reference_board

    async def broken(*args, **kwargs):
        return None

    monkeypatch.setattr(CharacterAssets, "_compose_character_reference_board", broken)
    job = await p.request_image_job(
        pid,
        card["id"],
        expected_version=approved["projectVersion"],
        operation_id="views-board",
        purpose="views",
    )
    assert (await p.run_image_job(job["id"]))["status"] == "recoverable"
    assert calls.count("submit") == 4

    monkeypatch.setattr(CharacterAssets, "_compose_character_reference_board", original)
    await p.recover_image_job(pid, job["id"])
    assert (await p.run_image_job(job["id"]))["status"] == "succeeded"
    assert calls.count("submit") == 4


async def test_invalid_download_with_known_task_recovers_without_new_submission(images):
    p, pid, _, _, calls, _ = images
    original = p._reference_image_provider._transport
    bad_download = True

    async def corrupt(req):
        if bad_download and req.url.path == "/result.png":
            return httpx.Response(200, content=b"not an image")
        return await original.handle_async_request(req)

    p._reference_image_provider._transport = httpx.MockTransport(corrupt)
    job = await request(images)
    assert (await p.run_image_job(job["id"]))["status"] == "recoverable"
    bad_download = False
    await p.recover_image_job(pid, job["id"])
    assert (await p.run_image_job(job["id"]))["status"] == "succeeded"
    assert calls.count("submit") == 1
