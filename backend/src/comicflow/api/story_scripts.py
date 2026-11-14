"""Story/script HTTP routes; model binding and authorization stay request scoped."""
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Header
from fastapi.responses import StreamingResponse

from comicflow.api.schemas import (
    GuidedAnswerRequest,
    ScriptUpdateRequest,
    ShotCreateRequest,
    ShotOrderRequest,
    StoryTextUpdateRequest,
    VersionedRequest,
)
from comicflow.api.text_stream import text_response
from comicflow.production.pipeline import ProductionPipeline


def story_script_router(
    pipeline: Callable[[], ProductionPipeline],
    require_project_access: Callable[[str, str | None], Awaitable[None]],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/projects/{project_id}/script")
    async def generate_script(
        project_id: str,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().generate_script(
            project_id, idempotency_key=idempotency_key
        )


    @router.post("/api/projects/{project_id}/story", response_model=None)
    async def generate_story_text(
        project_id: str,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_user_id: str | None = Header(default=None),
        accept: str | None = Header(default=None),
    ) -> dict[str, object] | StreamingResponse:
        await require_project_access(project_id, x_user_id)
        selected = pipeline()
        return await text_response(accept, lambda: selected.generate_story_text(
            project_id, idempotency_key=idempotency_key,
        ))


    @router.patch("/api/projects/{project_id}/story")
    async def update_story_text(
        project_id: str,
        payload: StoryTextUpdateRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().update_story_text(
            project_id, payload.story_text, expected_version=payload.expected_version
        )


    @router.post("/api/projects/{project_id}/script/guidance")
    async def ask_guided_question(
        project_id: str, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().ask_guided_question(project_id)


    @router.post("/api/projects/{project_id}/script/guidance/answer")
    async def answer_guided_question(
        project_id: str,
        payload: GuidedAnswerRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().answer_guided_question(project_id, payload.answer)


    @router.post("/api/projects/{project_id}/script/guidance/skip")
    async def skip_guided_question(
        project_id: str, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().skip_guided_question(project_id)


    @router.post("/api/projects/{project_id}/script/detail")
    async def generate_detailed_script(
        project_id: str, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().generate_detailed_script(project_id)


    @router.post("/api/projects/{project_id}/script/split")
    async def split_script(
        project_id: str, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().split_script(project_id)


    @router.post("/api/projects/{project_id}/script/preview", response_model=None)
    async def preview_script(
        project_id: str, x_user_id: str | None = Header(default=None),
        accept: str | None = Header(default=None),
    ) -> dict[str, object] | StreamingResponse:
        await require_project_access(project_id, x_user_id)
        selected = pipeline()
        return await text_response(accept, lambda: selected.preview_script(project_id))


    @router.put('/api/projects/{project_id}/script/preview')
    async def commit_script_preview(
        project_id: str, payload: ScriptUpdateRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().commit_script_preview(
            project_id, payload.script, expected_version=payload.expected_version,
        )


    @router.get("/api/projects/{project_id}/versions")
    async def project_script_versions(
        project_id: str, x_user_id: str | None = Header(default=None)
    ) -> list[dict[str, object]]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().list_script_versions(project_id)


    @router.patch("/api/projects/{project_id}/script")
    async def update_script(
        project_id: str, payload: ScriptUpdateRequest, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().update_script(
            project_id, payload.script, expected_version=payload.expected_version
        )


    @router.post("/api/projects/{project_id}/script/confirm")
    async def confirm_script(
        project_id: str, payload: VersionedRequest, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().confirm_script(
            project_id, expected_version=payload.expected_version
        )


    @router.post("/api/projects/{project_id}/script/shots", status_code=201)
    async def add_shot(
        project_id: str,
        payload: ShotCreateRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().add_shot(
            project_id, payload.shot, expected_version=payload.expected_version
        )


    @router.post("/api/projects/{project_id}/script/shots/{shot_id}/duplicate")
    async def duplicate_shot(
        project_id: str,
        shot_id: str,
        payload: VersionedRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().duplicate_shot(
            project_id, shot_id, expected_version=payload.expected_version
        )


    @router.delete("/api/projects/{project_id}/script/shots/{shot_id}")
    async def delete_shot(
        project_id: str,
        shot_id: str,
        payload: VersionedRequest,
        x_user_id: str | None = Header(default=None),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().delete_shot(
            project_id, shot_id, expected_version=payload.expected_version
        )


    @router.put("/api/projects/{project_id}/script/shots/order")
    async def reorder_shots(
        project_id: str, payload: ShotOrderRequest, x_user_id: str | None = Header(default=None)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().reorder_shots(
            project_id, payload.shot_ids, expected_version=payload.expected_version
        )


    return router
