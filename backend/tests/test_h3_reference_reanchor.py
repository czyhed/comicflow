"""Test H3 reference reanchor logic for continuity + character references."""
from __future__ import annotations

import pytest
from comicflow.domain.models import CreateProject, JsonObject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.minimax_h3 import MinimaxH3Provider


class _Store:
    async def presigned_get_url(self, key: str, expires_in: int = 900) -> str:
        return f"https://assets.test/{key}"


class _CapturingH3(MinimaxH3Provider):
    def __init__(self) -> None:
        super().__init__(api_key="offline", prompt_mode='context-ir')
        self.shot: JsonObject | None = None
        self.characters: list[JsonObject] | None = None

    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject], **kwargs
    ) -> JsonObject:
        self.shot = shot
        self.characters = character_inputs
        return {
            "id": f"video-{shot['id']}",
            "shotId": shot["id"],
            "type": "dynamic-video",
            "mediaType": "video",
            "provider": "minimax",
        }


@pytest.mark.asyncio
async def test_h3_uses_ref2va_when_cascading_with_character_references():
    """
    When using MiniMax H3 with:
    - A previous shot (cascade context)
    - Character references available
    - No explicit keyframe

    The system should use ref2va mode, which allows:
    - Previous shot tail frame as continuity reference
    - Character reference images for consistency
    """
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create a project with a manual script
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个勇敢的英雄在神秘的森林中探险，寻找传说中的宝藏。",
            mode="import_story",
            duration_sec=30,
        )
    )
    project_id = created["project"]["id"]

    # Add a character with reference image
    await pipeline._character_repository.save(
        {
            "id": "c1",
            "name": "英雄",
            "appearance": "勇敢的战士",
            "clothing": "盔甲",
            "personality": "勇敢",
            "voice": {},
            "referenceImageObjectKey": "characters/c1.png",
        }
    )

    # Set up a script with two shots in the same scene
    record = await pipeline._repository.get(project_id)
    assert record is not None
    record.project["script"] = {
        "scenes": [{"id": "scene1", "shotIds": ["s1", "s2"]}],
        "shots": [
            {"id": "s1", "durationSec": 5, "characterIds": ["c1"]},
            {"id": "s2", "durationSec": 5, "characterIds": ["c1"], 'action': '走进森林'},
        ],
    }
    # Simulate that first shot already has a video with tail frame
    record.project["visualAssets"] = [{
        "id": "video-s1",
        "shotId": "s1",
        "mediaType": "video",
        "valid": True,
        "lastFrameObjectKey": "visuals/s1/last_frame.jpg",
    }]
    await pipeline._repository.save(record)

    # Set up capturing provider and asset store
    pipeline._asset_store = _Store()
    provider = _CapturingH3()
    pipeline.set_video_provider(provider)

    # Generate second shot
    await pipeline.generate_shot_visual(
        project_id, "s2", expected_version=record.project["version"]
    )

    # Verify that ref2va mode was used
    assert provider.shot is not None
    assert provider.shot["generationMode"] == "ref2va"

    # Verify continuity reference is present
    assert "referenceImages" in provider.shot
    assert any(
        ref.get("view") == "continuity-anchor"
        for ref in provider.shot["referenceImages"]
    )
    assert any(
        ref.get("objectKey") == "visuals/s1/last_frame.jpg"
        for ref in provider.shot["referenceImages"]
    )

    # Verify character reference is preserved
    assert provider.characters is not None
    assert len(provider.characters) == 1
    assert provider.characters[0]["id"] == "c1"
    assert "referenceImageObjectKey" in provider.characters[0]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
