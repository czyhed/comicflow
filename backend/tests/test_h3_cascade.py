from __future__ import annotations

import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject, JsonObject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.h3_skill import reference_plan
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
            "id": "video-s2",
            "shotId": "s2",
            "type": "dynamic-video",
            "mediaType": "video",
            "provider": "minimax",
        }


async def _cascade_project() -> tuple[object, str, JsonObject]:
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜，学生在车站等待。",
            mode="import_story",
            duration_sec=30,
        )
    )
    project_id = created["project"]["id"]
    await pipeline._character_repository.save(
        {
            "id": "c1",
            "name": "学生",
            "appearance": "短发",
            "clothing": "外套",
            "personality": "沉稳",
            "voice": {},
            "referenceImageObjectKey": "characters/c1.png",
        }
    )
    record = await pipeline._repository.get(project_id)
    assert record is not None
    record.project["script"] = {
        "scenes": [{"id": "scene1", "shotIds": ["s1", "s2"]}],
        "shots": [
            {"id": "s1", "durationSec": 5, "characterIds": ["c1"], "action": "走近车站"},
            {"id": "s2", "durationSec": 5, "generationMode": "ref2va",
             "characterIds": ["c1"], "action": "走近车站"},
        ],
    }
    record.project["visualAssets"] = [{
        "id": "video-s1",
        "shotId": "s1",
        "mediaType": "video",
        "valid": True,
        "lastFrameObjectKey": "visuals/s1/last_frame.jpg",
    }]
    await pipeline._repository.save(record)
    pipeline._asset_store = _Store()
    return pipeline, project_id, record.project


@pytest.mark.asyncio
async def test_h3_cascade_uses_previous_tail_without_character_images() -> None:
    """
    When cascading with character references available, H3 now uses ref2va mode
    to preserve both continuity (tail frame) and consistency (character refs).

    This is a behavior change from the previous i2va-only cascade approach.
    """
    pipeline, project_id, project = await _cascade_project()
    provider = _CapturingH3()
    pipeline.set_video_provider(provider)

    await pipeline.generate_shot_visual(
        project_id, "s2", expected_version=project["version"]
    )

    assert provider.shot is not None
    # Now uses ref2va because character c1 has referenceImageObjectKey
    assert provider.shot["generationMode"] == "ref2va"
    # Tail frame is now in referenceImages, not as firstFrame
    assert "referenceImages" in provider.shot
    assert any(
        ref.get("objectKey") == "visuals/s1/last_frame.jpg"
        for ref in provider.shot["referenceImages"]
    )
    assert provider.characters is not None
    assert provider.characters[0]["id"] == "c1"
    # Character reference is now preserved
    assert "referenceImageObjectKey" in provider.characters[0]


@pytest.mark.asyncio
async def test_h3_new_character_reanchors_with_tail_and_current_references() -> None:
    pipeline, project_id, project = await _cascade_project()
    await pipeline._character_repository.save(
        {
            "id": "c2",
            "name": "店员",
            "appearance": "齐肩黑发，圆脸",
            "clothing": "绿色便利店制服",
            "personality": "警觉",
            "voice": {},
            "referenceImageObjectKey": "characters/c2.png",
        }
    )
    record = await pipeline._repository.get(project_id)
    assert record is not None
    record.project["script"]["shots"][1]["characterIds"] = ["c1", "c2"]
    await pipeline._repository.save(record)
    provider = _CapturingH3()
    pipeline.set_video_provider(provider)

    await pipeline.generate_shot_visual(
        project_id, "s2", expected_version=project["version"]
    )

    assert provider.shot is not None
    assert provider.shot["generationMode"] == "ref2va"
    assert "firstFrameUrl" not in provider.shot
    assert provider.shot["referenceImages"][0]["objectKey"] == (
        "visuals/s1/last_frame.jpg"
    )
    assert provider.shot["referenceImages"][0]["view"] == "continuity-anchor"
    assert provider.characters is not None
    assert [item["id"] for item in provider.characters] == ["c1", "c2"]
    assert all("referenceImageObjectKey" in item for item in provider.characters)
    plan = reference_plan(provider.shot, provider.characters)
    assert plan["mode"] == "ref2va"
    assert all(item["role"] == "reference_image" for item in plan["images"])
    assert not any(item["role"] == "first_frame" for item in plan["images"])


@pytest.mark.asyncio
async def test_h3_cascade_blocks_when_previous_tail_is_missing() -> None:
    pipeline, project_id, project = await _cascade_project()
    record = await pipeline._repository.get(project_id)
    assert record is not None
    record.project["visualAssets"][0].pop("lastFrameObjectKey")
    await pipeline._repository.save(record)
    provider = _CapturingH3()
    pipeline.set_video_provider(provider)

    with pytest.raises(DomainError, match="CASCADE_FRAME_MISSING"):
        await pipeline.generate_shot_visual(
            project_id, "s2", expected_version=project["version"]
        )

    assert provider.shot is None


async def test_explicit_strict_continuation_preserves_mode_through_adoption():
    pipeline, pid, project = await _cascade_project()
    class StoredH3(_CapturingH3):
        async def generate(self, shot, characters, **kwargs):
            return {**await super().generate(shot, characters, **kwargs), 'objectKey': 's2.mp4'}

    class ExistingStore(_Store):
        async def exists(self, key):
            return True

    pipeline._asset_store = ExistingStore()
    provider = StoredH3()
    pipeline.set_video_provider(provider)
    preview = await pipeline.preview_shot_visual(
        pid, 's2', expected_version=project['version'], continuity_mode='previous-tail',
    )
    assert preview['ready']
    job = await pipeline.request_video_job(
        pid, 's2', expected_version=project['version'], operation_id='strict',
        continuity_mode='previous-tail', preflight_fingerprint=preview['fingerprint'],
    )
    await pipeline.run_video_job(job['id'])
    assert provider.shot['generationMode'] == 'i2va'
    assert provider.shot['firstFrameObjectKey'] == 'visuals/s1/last_frame.jpg'
    assert 'referenceImages' not in provider.shot
    assert 'referenceImageObjectKey' not in provider.characters[0]
    assert provider.characters[0]['name'] == '学生'
    adopted = await pipeline.adopt_video_job(pid, job['id'])
    assert adopted['result']['adopted']


@pytest.mark.parametrize('shot_id, explicit', [('s1', False), ('s2', True)])
async def test_strict_continuation_rejects_missing_predecessor_or_explicit_frame(shot_id, explicit):
    pipeline, pid, project = await _cascade_project()
    pipeline.set_video_provider(_CapturingH3())
    if explicit:
        record = await pipeline._repository.get(pid)
        record.project['script']['shots'][1]['firstFrameUrl'] = 'https://assets.test/explicit.jpg'
        await pipeline._repository.save(record)
    preview = await pipeline.preview_shot_visual(
        pid, shot_id, expected_version=project['version'], continuity_mode='previous-tail',
    )
    assert not preview['ready']
    assert preview['errors'] == ['CONTINUITY_MODE_UNAVAILABLE']


@pytest.mark.asyncio
async def test_h3_new_scene_uses_all_current_references_as_anchor() -> None:
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜，学生在车站遇到陌生人。",
            mode="import_story",
            duration_sec=30,
        )
    )
    project_id = created["project"]["id"]
    for character_id, name in (("c1", "学生"), ("c2", "陌生人")):
        await pipeline._character_repository.save(
            {
                "id": character_id,
                "name": name,
                "appearance": "短发",
                "clothing": "深色外套",
                "personality": "沉稳",
                "voice": {},
                "referenceImageObjectKey": f"characters/{character_id}.png",
            }
        )
    record = await pipeline._repository.get(project_id)
    assert record is not None
    record.project["script"] = {
        "scenes": [
            {"id": "scene1", "shotIds": ["s1"]},
            {
                "id": "scene2",
                "shotIds": ["s2"],
                "backgroundImageObjectKey": "backgrounds/scene2.png",
            },
        ],
        "shots": [
            {"id": "s1", "durationSec": 5, "characterIds": ["c1"], "action": "走近车站"},
            # Script generation may label every first frame as i2va. A new
            # scene with approved references must become a ref2va anchor.
            {"id": "s2", "durationSec": 5, "generationMode": "i2va",
             "characterIds": ["c1", "c2"], "action": "走进车站"},
        ],
    }
    await pipeline._repository.save(record)
    pipeline._asset_store = _Store()
    provider = _CapturingH3()
    pipeline.set_video_provider(provider)

    await pipeline.generate_shot_visual(
        project_id, "s2", expected_version=record.project["version"]
    )

    assert provider.shot is not None
    assert provider.shot["generationMode"] == "ref2va"
    assert "firstFrameUrl" not in provider.shot
    assert provider.shot["referenceImages"][0]["objectKey"] == "backgrounds/scene2.png"
    assert provider.characters is not None
    assert [item["id"] for item in provider.characters] == ["c1", "c2"]
    assert all("referenceImageObjectKey" in item for item in provider.characters)
