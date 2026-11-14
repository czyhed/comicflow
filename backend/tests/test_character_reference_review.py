"""Character reference review and image-edit workflow tests."""

from __future__ import annotations

from copy import deepcopy

import pytest
from comicflow.domain.models import CreateProject, JsonObject
from comicflow.infrastructure.memory import create_memory_runtime


class RecordingImageProvider:
    def __init__(self) -> None:
        self.calls: list[JsonObject] = []

    async def generate(self, shot: JsonObject, character_inputs: list[JsonObject]) -> JsonObject:
        del character_inputs
        self.calls.append(deepcopy(shot))
        return {
            "mediaType": "image",
            "sourceUrl": f"https://assets.test/{shot['id']}.png",
            "provider": "test-image",
        }


async def _character_pipeline() -> tuple[object, RecordingImageProvider, str, JsonObject]:
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里，年轻人等待一封重要的信。",
            duration_sec=30,
            mode="import_story",
        )
    )
    project_id = created["project"]["id"]
    character = {
        "id": "c1",
        "projectId": project_id,
        "name": "林小雨",
        "appearance": "黑色短发，清晰五官",
        "clothing": "蓝色外套",
        "personality": "沉静",
        "voice": {},
        "revision": 0,
    }
    await pipeline._character_repository.save(character)
    provider = RecordingImageProvider()
    pipeline._reference_image_provider = provider
    record = await pipeline._repository.get(project_id)
    assert record is not None
    return pipeline, provider, project_id, record.project


@pytest.mark.asyncio
async def test_candidate_image_needs_approval_before_becoming_formal_reference() -> None:
    pipeline, provider, project_id, project = await _character_pipeline()

    result = await pipeline.generate_character_reference_candidate(
        project_id, "c1", expected_version=project["version"]
    )

    saved = await pipeline._character_repository.get("c1")
    assert saved is not None
    assert result["candidate"]["status"] == "candidate"
    assert saved["referenceImageCandidate"]["id"] == result["candidate"]["id"]
    assert "referenceImageUrl" not in saved
    assert provider.calls[0]["imagePurpose"] == "character-reference"

    approved = await pipeline.approve_character_reference_candidate(
        project_id,
        "c1",
        result["candidate"]["id"],
        expected_version=result["projectVersion"],
    )
    saved = await pipeline._character_repository.get("c1")
    assert saved is not None
    assert approved["character"]["referenceImageStatus"] == "approved"
    assert saved["referenceImageUrl"] == result["candidate"]["url"]
    assert saved["referenceImageCandidate"] is None


@pytest.mark.asyncio
async def test_candidate_regeneration_preserves_approved_image_until_new_approval() -> None:
    pipeline, _provider, project_id, project = await _character_pipeline()
    first = await pipeline.generate_character_reference_candidate(
        project_id, "c1", expected_version=project["version"]
    )
    approved = await pipeline.approve_character_reference_candidate(
        project_id, "c1", first["candidate"]["id"], expected_version=first["projectVersion"]
    )
    second = await pipeline.generate_character_reference_candidate(
        project_id, "c1", expected_version=approved["projectVersion"]
    )

    saved = await pipeline._character_repository.get("c1")
    assert saved is not None
    assert saved["referenceImageUrl"] == first["candidate"]["url"]
    assert saved["referenceImageCandidate"]["id"] == second["candidate"]["id"]
    assert second["candidate"]["id"] != first["candidate"]["id"]


@pytest.mark.asyncio
async def test_three_views_use_approved_image_as_the_only_edit_input() -> None:
    pipeline, provider, project_id, project = await _character_pipeline()
    candidate = await pipeline.generate_character_reference_candidate(
        project_id, "c1", expected_version=project["version"]
    )
    approved = await pipeline.approve_character_reference_candidate(
        project_id, "c1", candidate["candidate"]["id"], expected_version=candidate["projectVersion"]
    )

    result = await pipeline.generate_character_reference_views(
        project_id, "c1", expected_version=approved["projectVersion"]
    )

    saved = await pipeline._character_repository.get("c1")
    assert saved is not None
    assert [item["view"] for item in result["views"]] == ["front", "three-quarter", "profile"]
    assert [item["view"] for item in saved["referenceViews"]] == [
        "front", "three-quarter", "profile"
    ]
    for call in provider.calls[1:]:
        assert call["imagePurpose"] == "character-reference-view"
        assert call["sourceImageUrl"] == candidate["candidate"]["url"]
        assert call["sourceImageObjectKey"] is None
        assert call["view"] in {"front", "three-quarter", "profile"}
