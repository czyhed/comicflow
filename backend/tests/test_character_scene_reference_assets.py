"""Tests for character reference image and scene background image generation."""

from __future__ import annotations

import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


@pytest.mark.asyncio
async def test_confirmation_never_generates_images_and_explicit_scene_action_does():
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    calls = []

    class Images:
        async def generate(self, shot, characters):
            calls.append(shot)
            return {"mediaType": "image", "sourceUrl": "https://assets.test/scene.png"}

    pipeline.set_reference_image_provider(Images())
    created = await pipeline.create_project(CreateProject(
        input_type="story", story="主角在森林中寻找秘密。", duration_sec=30, mode="guided",
    ))
    pid = created["project"]["id"]
    await pipeline.generate_script(pid)
    snapshot = await pipeline.get_snapshot(pid)
    confirmed = await pipeline.confirm_script(pid, expected_version=snapshot["project"]["version"])
    assert calls == [], "Script confirmation must not spend image quota"
    assert confirmed["project"]["stage"] == "storyboard-ready"
    scene = confirmed["script"]["scenes"][0]
    generated = await pipeline.generate_project_reference(
        pid, "scenes", scene["id"], expected_version=confirmed["project"]["version"],
    )
    assert len(calls) == 1
    assert calls[0]["skillExecution"]
    saved = await pipeline.get_snapshot(pid)
    assert saved["project"]["script"]["scenes"][0]["backgroundImageMediaType"] == "image"
    await pipeline.confirm_script(pid, expected_version=generated["projectVersion"])
    reused = await pipeline.generate_project_reference(
        pid, "scenes", scene["id"], expected_version=generated["projectVersion"],
    )
    assert reused["reused"] is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_confirm_script_preserves_character_cards():
    """Verify that script confirmation preserves its character cards."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create project in guided mode
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个关于勇气的故事。小明在城市中寻找希望。",
            duration_sec=30,
            mode="guided",  # Changed to guided mode
        )
    )
    project_id = created["project"]["id"]

    # Generate script
    await pipeline.generate_script(project_id)
    project = (await pipeline._repository.get(project_id)).project
    version = project["version"]

    # Confirm the script without generating media.
    result = await pipeline.confirm_script(project_id, expected_version=version)

    # Get the script to check characters
    script = result["script"]
    assert script is not None
    # The stage is on the project, not the script
    assert result["project"]["stage"] == "storyboard-ready"

    # Get unique character IDs from shots
    character_ids: set[str] = set()
    for shot in script.get("shots", []):
        for char_id in shot.get("characterIds", []):
            character_ids.add(char_id)

    # Verify that referenced character cards remain available.

    for char_id in character_ids:
        character = await pipeline._character_repository.get(char_id)
        assert character is not None
        # The card is preserved independently of image generation.


@pytest.mark.asyncio
async def test_confirm_script_preserves_scenes():
    """Verify that script confirmation preserves scene definitions."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create project in guided mode
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个关于探索的故事。主角在森林中发现秘密。",
            duration_sec=30,
            mode="guided",  # Changed to guided mode
        )
    )
    project_id = created["project"]["id"]

    # Generate script
    await pipeline.generate_script(project_id)
    project = (await pipeline._repository.get(project_id)).project
    version = project["version"]

    # Confirm the script without generating media.
    result = await pipeline.confirm_script(project_id, expected_version=version)

    # Get the script to check scenes
    script = result["script"]
    assert script is not None
    # The stage is on the project, not the script
    assert result["project"]["stage"] == "storyboard-ready"

    # Verify that scenes exist
    scenes = script.get("scenes", [])
    assert len(scenes) > 0

    # In mock mode, backgroundImageUrl may not be set, but scenes should exist
    for scene in scenes:
        assert "id" in scene
        # Location or time should be present
        assert "location" in scene or "time" in scene


@pytest.mark.asyncio
async def test_character_reference_reuse():
    """Verify that existing character reference images are not overwritten."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline

    # Create project in guided mode
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="测试角色的故事。小明在城市中探险。",
            duration_sec=30,
            mode="guided",  # Changed to guided mode
        )
    )
    project_id = created["project"]["id"]

    # Generate script
    await pipeline.generate_script(project_id)
    project = (await pipeline._repository.get(project_id)).project

    # Get a character and set a reference image URL manually
    script = project["script"]
    character_ids: set[str] = set()
    for shot in script.get("shots", []):
        for char_id in shot.get("characterIds", []):
            character_ids.add(char_id)

    if character_ids:
        char_id = list(character_ids)[0]
        character = await pipeline._character_repository.get(char_id)

        # Set a reference image URL
        character["referenceImageUrl"] = "https://example.com/ref.png"
        character["referenceImageObjectKey"] = "test/ref.png"
        await pipeline._character_repository.save(character)

        version = project["version"]

        # Confirm script
        await pipeline.confirm_script(project_id, expected_version=version)

        # Verify the reference image URL was NOT overwritten
        updated_character = await pipeline._character_repository.get(char_id)
        assert updated_character["referenceImageUrl"] == "https://example.com/ref.png"
        assert updated_character["referenceImageObjectKey"] == "test/ref.png"


@pytest.mark.asyncio
async def test_confirm_script_handles_missing_asset_store():
    """Verify that script confirmation gracefully handles missing asset store."""
    from comicflow.infrastructure.memory import (
        InMemoryCharacterRepository,
        InMemoryProjectRepository,
    )
    from comicflow.production.pipeline import ProductionPipeline
    from comicflow.providers.mock import MockTextProvider
    from comicflow.providers.mock_media import (
        MockCompositionProvider,
        MockDynamicVisualProvider,
        MockLipSyncProvider,
        MockTtsProvider,
    )

    # Create pipeline without asset store
    pipeline = ProductionPipeline(
        repository=InMemoryProjectRepository(),
        character_repository=InMemoryCharacterRepository(),
        text_provider=MockTextProvider(),
        dynamic_visual_provider=MockDynamicVisualProvider(),
        tts_provider=MockTtsProvider(),
        lip_sync_provider=MockLipSyncProvider(),
        composition_provider=MockCompositionProvider(),
        asset_store=None,  # No asset store
    )

    # Create project in guided mode
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="测试故事。主角在城市中冒险。",
            duration_sec=30,
            mode="guided",  # Changed to guided mode
        )
    )
    project_id = created["project"]["id"]

    # Generate script
    await pipeline.generate_script(project_id)
    project = (await pipeline._repository.get(project_id)).project
    version = project["version"]

    # Confirm script should succeed even without asset store
    # Confirmation does not require media storage.
    result = await pipeline.confirm_script(project_id, expected_version=version)
    assert result["script"] is not None
    # The stage is on the project, not the script
    assert result["project"]["stage"] == "storyboard-ready"
