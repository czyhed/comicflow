import asyncio
import os
import sys
import time

import boto3
import pytest
from comicflow.api.app import create_app, create_configured_runtime
from comicflow.infrastructure.database import create_session_factory
from httpx import ASGITransport, AsyncClient
from redis import Redis

pytestmark = pytest.mark.skipif(
    os.getenv("COMICFLOW_INFRA_SMOKE") != "1",
    reason="set COMICFLOW_INFRA_SMOKE=1 to run Docker-backed smoke tests",
)


async def test_local_infrastructure_completes_outbox_worker_and_export() -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://comicflow:comicflow_dev_only@127.0.0.1:15432/comicflow",
    )
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:16379/0")
    os.environ["COMICFLOW_RUNTIME"] = "postgresql"
    os.environ["DATABASE_URL"] = database_url
    os.environ["REDIS_URL"] = redis_url
    os.environ["S3_ENDPOINT"] = os.environ.get("S3_ENDPOINT", "http://127.0.0.1:19000")
    os.environ["S3_BUCKET"] = os.environ.get("S3_BUCKET", "comicflow")
    os.environ["S3_ACCESS_KEY_ID"] = os.environ.get("S3_ACCESS_KEY_ID", "comicflow")
    os.environ["S3_SECRET_ACCESS_KEY"] = os.environ.get(
        "S3_SECRET_ACCESS_KEY", "comicflow_dev_only"
    )
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:19000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID", "comicflow"),
        aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", "comicflow_dev_only"),
        region_name="us-east-1",
    )
    bucket = os.environ.get("S3_BUCKET", "comicflow")
    buckets = [item["Name"] for item in s3.list_buckets().get("Buckets", [])]
    if bucket not in buckets:
        s3.create_bucket(Bucket=bucket)
    assert bucket in [item["Name"] for item in s3.list_buckets().get("Buckets", [])]
    assert Redis.from_url(redis_url).ping() is True

    runtime = create_configured_runtime()
    app = create_app(runtime)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
                "durationSec": 60,
                "mode": "guided",
            },
        )
        assert created.status_code == 201
        project_id = created.json()["project"]["id"]
        generated = await client.post(f"/api/projects/{project_id}/script")
        composition = await client.post(
            f"/api/projects/{project_id}/composition",
            json={
                "expectedVersion": generated.json()["project"]["version"],
                "idempotencyKey": "infra-v1",
            },
        )
        assert composition.status_code == 202
        job_id = composition.json()["id"]
        repeat = await client.post(
            f"/api/projects/{project_id}/composition",
            json={
                "expectedVersion": generated.json()["project"]["version"],
                "idempotencyKey": "infra-v1",
            },
        )
        assert repeat.status_code == 202
        assert repeat.json()["id"] == job_id

    worker_env = os.environ.copy()
    worker_env["PYTHONPATH"] = os.pathsep.join(["backend/src", worker_env.get("PYTHONPATH", "")])
    worker_env["DATABASE_URL"] = database_url
    worker_env["REDIS_URL"] = redis_url
    worker_env["S3_ENDPOINT"] = os.environ.get("S3_ENDPOINT", "http://127.0.0.1:19000")
    worker_env["S3_BUCKET"] = bucket
    worker_env["S3_ACCESS_KEY_ID"] = os.environ.get("S3_ACCESS_KEY_ID", "comicflow")
    worker_env["S3_SECRET_ACCESS_KEY"] = os.environ.get(
        "S3_SECRET_ACCESS_KEY", "comicflow_dev_only"
    )
    # Configure the module-level Celery app used by publish_to_celery before
    # importing it, otherwise it defaults to localhost:6379.
    os.environ["REDIS_URL"] = redis_url
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "celery",
        "-A",
        "comicflow.worker.celery_app:celery_app",
        "worker",
        "--pool=solo",
        "--loglevel=WARNING",
        env=worker_env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    engine, sessions = create_session_factory(database_url)
    try:
        import comicflow.worker.celery_app as celery_module
        from comicflow.infrastructure.database import SqlAlchemyProjectRepository
        from comicflow.worker.celery_app import create_celery_app, publish_to_celery
        from comicflow.worker.outbox import OutboxDispatcher

        celery_module.celery_app = create_celery_app(redis_url)
        repository = SqlAlchemyProjectRepository(sessions)
        dispatcher = OutboxDispatcher(repository, publish_to_celery)
        # Compose Beat may publish this event before the test's dispatcher gets
        # the database claim, so the first pass can legitimately find nothing.
        dispatch_count = await dispatcher.dispatch_once()
        if dispatch_count == 0:
            pending = await repository.pending_outbox()
            assert not any(item["payload"].get("jobId") == job_id for item in pending)
    finally:
        await engine.dispose()

    try:
        deadline = time.monotonic() + 20
        completed = None
        while time.monotonic() < deadline:
            snapshot = await runtime.pipeline.get_snapshot(project_id)
            completed = next(
                (item for item in snapshot["jobs"] if item["id"] == job_id), None
            )
            if completed and completed["status"] == "succeeded":
                break
            await asyncio.sleep(0.5)
        assert completed is not None
        assert completed["status"] == "succeeded"
        downloads = completed["exportManifest"]["downloads"]
        for filename in ("video.mp4", "cover.jpg", "subtitles.srt"):
            assert filename in downloads
            s3.head_object(Bucket=bucket, Key=f"exports/{project_id}/{filename}")
    finally:
        worker.terminate()
        await asyncio.wait_for(worker.wait(), timeout=10)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(f"/api/projects/{project_id}/claim", headers={"X-User-Id": "infra-user"})
        export = await client.get(
            f"/api/projects/{project_id}/export", headers={"X-User-Id": "infra-user"}
        )
        assert export.status_code == 200
        assert export.json()["files"] == ["video.mp4", "cover.jpg", "subtitles.srt"]
        assert all(value.startswith("http") for value in export.json()["downloads"].values())
