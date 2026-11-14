"""Composition and export HTTP routes, preserving project/job access checks."""
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Header, Query

from comicflow.api.schemas import CompositionRequest
from comicflow.domain.errors import DomainError
from comicflow.production.pipeline import ProductionPipeline


def composition_router(
    pipeline: Callable[[], ProductionPipeline],
    require_project_access: Callable[[str, str | None], Awaitable[None]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/projects/{project_id}/export")
    async def export_package(
        project_id: str, job_id: str | None = Query(default=None),
        x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        if not x_user_id:
            raise DomainError("AUTH_REQUIRED")
        await require_project_access(project_id, x_user_id)
        return await pipeline().get_export_manifest(project_id, job_id=job_id)

    @router.post("/api/projects/{project_id}/composition", status_code=202)
    async def request_composition(
        project_id: str, payload: CompositionRequest, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().request_composition(
            project_id,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            shot_ids=payload.shot_ids,
            shot_trims=({sid: trim.model_dump(by_alias=True)
                         for sid, trim in payload.shot_trims.items()}
                        if payload.shot_trims else None),
        )

    @router.post("/api/projects/{project_id}/jobs/{job_id}/cancel")
    async def cancel_job(
        project_id: str,
        job_id: str,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        if not x_user_id:
            raise DomainError("AUTH_REQUIRED")
        snapshot = await pipeline().get_snapshot(project_id, user_id=x_user_id)
        if not any(job.get("id") == job_id for job in snapshot.get("jobs", [])):
            raise DomainError("JOB_NOT_FOUND")
        return await pipeline().cancel_job(job_id)

    return router
