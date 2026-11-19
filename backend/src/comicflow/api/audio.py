"""Explicit shot audio HTTP entry point with the existing access checks."""
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends

from comicflow.api.schemas import VersionedRequest
from comicflow.identity.request import current_user_id
from comicflow.production.pipeline import ProductionPipeline


def audio_router(
    pipeline: Callable[[], ProductionPipeline],
    require_project_access: Callable[[str, str | None], Awaitable[None]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/projects/{project_id}/shots/{shot_id}/audio")
    async def generate_audio(
        project_id: str,
        shot_id: str,
        payload: VersionedRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().generate_shot_audio(
            project_id, shot_id, expected_version=payload.expected_version
        )

    return router
