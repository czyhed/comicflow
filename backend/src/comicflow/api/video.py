"""Video HTTP endpoints; request-scoped model selection stays in app middleware."""
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Header

from comicflow.api.schemas import (
    RegenerationRequest,
    VideoJobRecoveryRequest,
    VideoJobRequest,
    VideoPreflightRequest,
    VisualGenerationRequest,
)
from comicflow.production.pipeline import ProductionPipeline


def video_router(
    pipeline: Callable[[], ProductionPipeline],
    require_project_access: Callable[[str, str | None], Awaitable[None]],
) -> APIRouter:
    router = APIRouter()

    @router.post('/api/projects/{project_id}/shots/{shot_id}/video-jobs', status_code=202)
    async def queue_video(
        project_id: str, shot_id: str, payload: VideoJobRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().request_video_job(
            project_id, shot_id, expected_version=payload.expected_version,
            operation_id=payload.operation_id, preflight_fingerprint=payload.preflight_fingerprint,
            continuity_mode=payload.continuity_mode,
        )

    @router.get('/api/projects/{project_id}/video-jobs')
    async def list_video_jobs(
        project_id: str, x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return {'items': await pipeline().list_video_jobs(project_id)}

    @router.get('/api/projects/{project_id}/video-jobs/{job_id}')
    async def get_video_job(
        project_id: str, job_id: str, x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().get_video_job(project_id, job_id)

    @router.post('/api/projects/{project_id}/video-jobs/{job_id}/recover', status_code=202)
    async def recover_video_job(
        project_id: str, job_id: str, payload: VideoJobRecoveryRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().recover_video_job(project_id, job_id, payload.task_id)

    @router.post('/api/projects/{project_id}/video-jobs/{job_id}/adopt')
    async def adopt_video_job(
        project_id: str, job_id: str, x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().adopt_video_job(project_id, job_id)

    @router.post('/api/projects/{project_id}/shots/{shot_id}/visual/preflight')
    async def preview_visual(
        project_id: str, shot_id: str, payload: VideoPreflightRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().preview_shot_visual(
            project_id, shot_id, expected_version=payload.expected_version,
            continuity_mode=payload.continuity_mode,
        )

    @router.post("/api/projects/{project_id}/shots/{shot_id}/visual")
    async def generate_visual(
        project_id: str,
        shot_id: str,
        payload: VisualGenerationRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().generate_shot_visual(
            project_id, shot_id, expected_version=payload.expected_version,
            preflight_fingerprint=payload.preflight_fingerprint,
        )

    @router.post("/api/projects/{project_id}/shots/{shot_id}/regenerate")
    async def regenerate_shot(
        project_id: str,
        shot_id: str,
        payload: RegenerationRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().regenerate_shot(
            project_id,
            shot_id,
            scope=payload.scope,
            expected_version=payload.expected_version,
        )

    return router
