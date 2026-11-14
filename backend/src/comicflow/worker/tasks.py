from __future__ import annotations

import asyncio
import os
from typing import Any

from comicflow.api.app import create_configured_runtime
from comicflow.infrastructure.database import SqlAlchemyProjectRepository, create_session_factory
from comicflow.providers.model_selection import selected_image_runtime, selected_runtime
from comicflow.worker.celery_app import celery_app, publish_to_celery
from comicflow.worker.outbox import OutboxDispatcher


@celery_app.task(  # type: ignore[untyped-decorator]
    name="comicflow.worker.run_job",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def run_job(self: Any, job_id: str) -> dict[str, object]:
    """Execute one persisted generation job; Celery retry handles transient failures."""
    del self
    async def execute() -> dict[str, object]:
        runtime = create_configured_runtime()
        record = await runtime.pipeline._repository.find_by_job(job_id)
        job = next((j for j in record.jobs if j['id'] == job_id), {}) if record else {}
        runtime = await selected_runtime(runtime, job.get('modelConfigRevision'))
        return await runtime.pipeline.run_job(job_id)
    return asyncio.run(execute())


@celery_app.task(  # type: ignore[untyped-decorator]
    name="comicflow.worker.advance_generation_session",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def advance_generation_session(
    self: Any, project_id: str, model_config_revision: int | None = None,
) -> dict[str, object]:
    """Advance one automatic production checkpoint without credentials in task args."""
    del self
    async def advance() -> dict[str, object]:
        runtime = await selected_runtime(create_configured_runtime(), model_config_revision)
        return await runtime.pipeline.advance_generation_session(project_id)
    return asyncio.run(advance())


@celery_app.task(name="comicflow.worker.dispatch_outbox")  # type: ignore[untyped-decorator]
def dispatch_outbox() -> int:
    """Publish committed outbox rows; rows are marked only after broker acceptance."""
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://comicflow:comicflow_dev_only@127.0.0.1:15432/comicflow",
    )

    async def dispatch() -> int:
        engine, sessions = create_session_factory(database_url)
        try:
            repository = SqlAlchemyProjectRepository(sessions)
            return await OutboxDispatcher(repository, publish_to_celery).dispatch_once()
        finally:
            await engine.dispose()

    return asyncio.run(dispatch())


@celery_app.task(name='comicflow.worker.run_video_job')  # type: ignore[untyped-decorator]
def run_video_job(job_id: str) -> dict[str, object]:
    """Redelivery is fenced in PostgreSQL; never auto-retry a provider submission."""
    async def execute() -> dict[str, object]:
        runtime = create_configured_runtime()
        return await execute_video_job(runtime, job_id)
    return asyncio.run(execute())


async def execute_video_job(runtime: Any, job_id: str) -> dict[str, object]:
    from uuid import uuid4

    from comicflow.domain.errors import DomainError
    from comicflow.production.video_jobs import public_job

    store = runtime.pipeline._video_job_store
    job = await store.get(job_id)
    if job is None:
        return {'id': job_id, 'status': 'missing'}
    try:
        selected = await selected_runtime(runtime, job['modelConfigRevision'])
    except DomainError as error:
        if job.get('asset'):
            # Saving a downloaded candidate needs no supplier credentials.
            return dict(await runtime.pipeline.run_video_job(job_id))
        token = uuid4().hex
        claimed = await store.claim(job_id, token)
        if claimed is not None:
            job = await store.checkpoint(job_id, token,
                'recoverable' if job.get('taskId') else 'failed',
                {'error': error.code, 'errorDetail': {}, 'resumeStage': job['status']})
        return dict(public_job(job))
    return dict(await selected.pipeline.run_video_job(job_id))


@celery_app.task(name='comicflow.worker.run_image_job')  # type: ignore[untyped-decorator]
def run_image_job(job_id: str) -> dict[str, object]:
    async def execute() -> dict[str, object]:
        return await execute_image_job(create_configured_runtime(), job_id)
    return asyncio.run(execute())


async def execute_image_job(runtime: Any, job_id: str) -> dict[str, object]:
    from uuid import uuid4

    from comicflow.domain.errors import DomainError
    from comicflow.production.image_jobs import public_job

    store = runtime.pipeline._image_job_store
    job = await store.get(job_id)
    if job is None:
        return {'id': job_id, 'status': 'missing'}
    try:
        selected = await selected_image_runtime(runtime, job['modelConfigRevision'])
    except DomainError as error:
        if job.get('providerAsset'):
            return dict(await runtime.pipeline.run_image_job(job_id))
        token = uuid4().hex
        if await store.claim(job_id, token) is not None:
            job = await store.checkpoint(job_id, token,
                'recoverable' if job.get('taskId') else 'failed', {'error': error.code})
        return dict(public_job(job))
    return dict(await selected.pipeline.run_image_job(job_id))
