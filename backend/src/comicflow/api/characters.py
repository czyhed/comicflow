"""Character HTTP routes with the existing request-scoped model bindings."""
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends

from comicflow.api.schemas import (
    CharacterPromptPreviewRequest,
    CharacterReferenceCandidateApprovalRequest,
    CharacterReferenceViewsRequest,
    ImageJobRequest,
    ShotCharactersRequest,
    VersionedRequest,
)
from comicflow.domain.models import Actor
from comicflow.identity.request import current_user_id
from comicflow.production.pipeline import ProductionPipeline


def character_router(
    pipeline: Callable[[], ProductionPipeline],
    require_project_access: Callable[[str, str | None], Awaitable[None]],
) -> APIRouter:
    router = APIRouter()

    @router.post('/api/projects/{project_id}/characters/{character_id}/image-jobs', status_code=202)
    async def queue_image(
        project_id: str, character_id: str, payload: ImageJobRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().request_image_job(project_id, character_id,
            expected_version=payload.expected_version, operation_id=payload.operation_id,
            purpose=payload.purpose, force=payload.force)

    @router.get('/api/projects/{project_id}/image-jobs')
    async def list_image_jobs(
        project_id: str, x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return {'items': await pipeline().list_image_jobs(project_id)}

    @router.get('/api/projects/{project_id}/image-jobs/{job_id}')
    async def get_image_job(
        project_id: str, job_id: str, x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().get_image_job(project_id, job_id)

    @router.post('/api/projects/{project_id}/image-jobs/{job_id}/recover', status_code=202)
    async def recover_image_job(
        project_id: str, job_id: str, x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().recover_image_job(project_id, job_id)

    @router.get("/api/characters")
    async def list_character_templates() -> list[dict[str, object]]:
        return await pipeline().list_character_templates()

    @router.get('/api/projects/{project_id}/characters')
    async def list_project_characters(
        project_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> list[dict[str, object]]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().list_project_characters(project_id)

    @router.post('/api/projects/{project_id}/characters/{character_id}/reference-candidate')
    async def generate_character_reference_candidate(
        project_id: str, character_id: str, payload: VersionedRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().generate_character_reference_candidate(
            project_id, character_id, expected_version=payload.expected_version
        )

    @router.post('/api/projects/{project_id}/characters/{character_id}/reference-candidate/approve')
    async def approve_character_reference_candidate(
        project_id: str, character_id: str,
        payload: CharacterReferenceCandidateApprovalRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().approve_character_reference_candidate(
            project_id,
            character_id,
            payload.candidate_id,
            expected_version=payload.expected_version,
        )

    @router.post('/api/projects/{project_id}/characters/{character_id}/reference-board/approve')
    async def approve_character_reference_board(
        project_id: str, character_id: str,
        payload: CharacterReferenceCandidateApprovalRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().approve_character_reference_board(
            project_id, character_id, payload.candidate_id,
            expected_version=payload.expected_version)

    @router.post('/api/projects/{project_id}/characters/{character_id}/reference-views')
    async def generate_character_reference_views(
        project_id: str, character_id: str,
        payload: CharacterReferenceViewsRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().generate_character_reference_views(
            project_id,
            character_id,
            expected_version=payload.expected_version,
            force=payload.force,
        )

    @router.post('/api/projects/{project_id}/characters/sync')
    async def sync_project_characters(
        project_id: str, payload: VersionedRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().sync_project_characters(
            project_id, expected_version=payload.expected_version
        )

    @router.post('/api/projects/{project_id}/characters/prompt-preview')
    async def preview_character_prompt(
        project_id: str, payload: CharacterPromptPreviewRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().preview_character_prompt(
            project_id, fields=payload.fields.model_dump(by_alias=True),
            instructions=payload.instructions, character_id=payload.character_id,
            expected_version=payload.expected_version, expected_revision=payload.expected_revision,
            purpose=payload.purpose, output_fields=payload.output_fields,
        )

    @router.post('/api/projects/{project_id}/characters', status_code=201)
    async def create_project_character(
        project_id: str, payload: dict[str, object],
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().save_project_character(project_id, payload)

    @router.patch('/api/projects/{project_id}/characters/{character_id}')
    async def update_project_character(
        project_id: str, character_id: str, payload: dict[str, object],
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().save_project_character(
            project_id, payload, character_id=character_id
        )

    @router.post("/api/characters", status_code=201)
    async def create_character(
        payload: dict[str, object],
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        actor = Actor.user(x_user_id or "local-creator")
        return await pipeline().create_character(payload, actor=actor)

    @router.patch("/api/characters/{character_id}")
    async def update_character(
        character_id: str,
        payload: dict[str, object],
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        return await pipeline().update_character(
            character_id, payload, actor=Actor.user(x_user_id or "local-creator")
        )

    @router.delete("/api/characters/{character_id}", status_code=204)
    async def delete_character(
        character_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> None:
        await pipeline().delete_character(
            character_id, actor=Actor.user(x_user_id or "local-creator")
        )

    @router.put("/api/projects/{project_id}/script/shots/{shot_id}/characters")
    async def assign_shot_characters(
        project_id: str,
        shot_id: str,
        payload: ShotCharactersRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await pipeline().assign_shot_characters(
            project_id,
            shot_id,
            payload.character_ids,
            expected_version=payload.expected_version,
        )

    return router
