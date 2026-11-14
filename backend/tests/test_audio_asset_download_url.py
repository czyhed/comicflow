"""Regression test for audio/visual asset downloadUrl enrichment (P0 silent failure)."""

from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


async def test_snapshot_enriches_valid_assets_with_download_urls() -> None:
    """Verify that get_snapshot presigns objectKey to downloadUrl for valid assets."""

    class FakeAssetStore:
        async def exists(self, object_key: str) -> bool:
            return bool(object_key)

        async def put_bytes(
            self, object_key: str, content: bytes, content_type: str
        ) -> str:
            return object_key

        async def presigned_get_url(
            self, object_key: str, expires_in: int = 900
        ) -> str:
            return f"https://assets.test/{object_key}"

    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    pipeline._asset_store = FakeAssetStore()  # type: ignore[assignment]

    # Create project and generate audio
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个年轻的程序员在深夜调试音频播放功能",
            duration_sec=30,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    script = await pipeline.generate_script(project_id)
    version = script["project"]["version"]
    shot_id = script["script"]["shots"][0]["id"]

    # Generate visual first (audio depends on it)
    visual_result = await pipeline.generate_shot_visual(
        project_id, shot_id, expected_version=version
    )
    await pipeline.adopt_video_job(project_id, visual_result["jobId"])
    version = visual_result["projectVersion"]

    # Generate audio
    await pipeline.generate_shot_audio(project_id, shot_id, expected_version=version)

    # Verify snapshot includes downloadUrl for valid assets
    snapshot = await pipeline.get_snapshot(project_id)

    visual_assets = [a for a in snapshot["visualAssets"] if a.get("valid")]
    audio_assets = [a for a in snapshot["audioAssets"] if a.get("valid")]

    assert len(visual_assets) == 1
    assert len(audio_assets) == 1

    visual_url = visual_assets[0].get("downloadUrl")
    audio_url = audio_assets[0].get("downloadUrl")

    # Mock asset store returns https://assets.test/{objectKey}
    assert isinstance(visual_url, str)
    assert visual_url.startswith("https://assets.test/")
    assert isinstance(audio_url, str)
    assert audio_url.startswith("https://assets.test/")

    # Verify caching: second call returns same URL
    snapshot2 = await pipeline.get_snapshot(project_id)
    assert snapshot2["audioAssets"][0]["downloadUrl"] == audio_url


async def test_snapshot_adds_poster_only_for_adopted_video_first_frames() -> None:
    class Store:
        async def presigned_get_url(self, object_key: str, expires_in: int = 900) -> str:
            return f"https://assets.test/{object_key}"

    pipeline = create_memory_runtime().pipeline
    pipeline._asset_store = Store()  # type: ignore[assignment]
    snapshot = {"visualAssets": [
        {"shotId": "s1", "valid": True, "objectKey": "v1.mp4",
         "firstFrameObjectKey": "visuals/s1/first_frame.jpg"},
        {"shotId": "s1", "status": "candidate", "valid": False, "objectKey": "v2.mp4",
         "firstFrameObjectKey": "visuals/s1/first_frame.jpg"},
        {"shotId": "s2", "valid": True, "objectKey": "v3.mp4"},
    ]}
    await pipeline._enrich_snapshot_with_asset_urls(snapshot)
    adopted, candidate, no_frame = snapshot["visualAssets"]
    assert adopted["posterUrl"] == "https://assets.test/visuals/s1/first_frame.jpg"
    assert "posterUrl" not in candidate and "posterUrl" not in no_frame
    assert candidate["downloadUrl"] == "https://assets.test/v2.mp4"
