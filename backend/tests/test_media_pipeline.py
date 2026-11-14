import asyncio
import importlib
import importlib.util
import json
import subprocess

import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock_media import MockDynamicVisualProvider


async def test_dynamic_shot_audio_timeline_and_export_are_one_production_flow() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    generated = await pipeline.generate_script(project_id)
    shot_id = generated["script"]["shots"][2]["id"]

    visual = await pipeline.generate_shot_visual(
        project_id, shot_id, expected_version=generated["project"]["version"]
    )
    await pipeline.adopt_video_job(project_id, visual["jobId"])
    audio = await pipeline.generate_shot_audio(
        project_id, shot_id, expected_version=visual["projectVersion"]
    )

    assert visual["asset"]["mediaType"] == "video"
    assert audio["timeline"]["dialogue"][0]["text"] == "你终于来了。"
    assert audio["timeline"]["lipSyncTrack"][0]["endMs"] == audio["asset"]["durationMs"]

    # Composition is gated on a complete film, so generate the remaining shots.
    version = audio["projectVersion"]
    for shot in generated["script"]["shots"]:
        if shot["id"] == shot_id:
            continue
        shot_visual = await pipeline.generate_shot_visual(
            project_id, str(shot["id"]), expected_version=version
        )
        await pipeline.adopt_video_job(project_id, shot_visual["jobId"])
        shot_audio = await pipeline.generate_shot_audio(
            project_id, str(shot["id"]), expected_version=shot_visual["projectVersion"]
        )
        version = shot_audio["projectVersion"]

    job = await pipeline.request_composition(
        project_id,
        expected_version=version,
        idempotency_key="export-v1",
    )
    completed = await pipeline.run_job(job["id"])
    snapshot = await pipeline.get_snapshot(project_id)

    assert completed["status"] == "succeeded"
    assert snapshot["exportManifest"]["files"] == [
        "video.mp4",
        "cover.jpg",
        "subtitles.srt",
    ]


async def test_scoped_audio_regeneration_preserves_visual_and_refreshes_timing() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="A rainy train mystery where a missing sister returns",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    generated = await pipeline.generate_script(project_id)
    shot_id = generated["script"]["shots"][2]["id"]
    visual = await pipeline.generate_shot_visual(
        project_id, shot_id, expected_version=generated["project"]["version"]
    )
    await pipeline.adopt_video_job(project_id, visual["jobId"])
    first = await pipeline.generate_shot_audio(
        project_id, shot_id, expected_version=visual["projectVersion"]
    )
    second = await pipeline.regenerate_shot(
        project_id, shot_id, scope="audio", expected_version=first["projectVersion"]
    )
    assert second["scope"] == "audio"
    assert second["asset"]["id"] != first["asset"]["id"]
    assert second["timeline"]["visualAssetId"] == visual["asset"]["id"]


async def test_scoped_regeneration_failure_keeps_previous_visual_asset_valid() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="A rainy train mystery where a missing sister returns",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    generated = await pipeline.generate_script(project_id)
    shot_id = generated["script"]["shots"][0]["id"]
    first = await pipeline.generate_shot_visual(
        project_id, shot_id, expected_version=generated["project"]["version"]
    )
    await pipeline.adopt_video_job(project_id, first["jobId"])

    class FailingVisual(MockDynamicVisualProvider):
        async def generate(
            self, shot: dict[str, object], character_inputs: list[dict[str, object]]
        ) -> dict[str, object]:
            raise RuntimeError("provider unavailable")

    pipeline._dynamic_visual_provider = FailingVisual()  # type: ignore[assignment]
    with pytest.raises(DomainError, match='PROVIDER_UNAVAILABLE'):
        await pipeline.regenerate_shot(
            project_id, shot_id, scope="visual", expected_version=first["projectVersion"]
        )
    snapshot = await pipeline.get_snapshot(project_id)
    assert any(
        asset["id"] == first["asset"]["id"] and asset["valid"] for asset in snapshot["visualAssets"]
    )


async def test_ffmpeg_composition_produces_six_second_vertical_delivery_package(
    tmp_path,
) -> None:
    module_spec = importlib.util.find_spec("comicflow.providers.ffmpeg")
    assert module_spec is not None, "the real FFmpeg composition provider is missing"
    provider_module = importlib.import_module("comicflow.providers.ffmpeg")
    provider = provider_module.FfmpegCompositionProvider()
    project = {
        "id": "project-export-contract",
        "script": {
            "title": "雨夜重逢",
            "shots": [
                {
                    "id": "shot-1",
                    "durationSec": 6,
                    "dialogue": "你终于来了。",
                }
            ],
        },
        "timelines": {
            "shot-1": {
                "durationMs": 6000,
                "subtitle": [{"text": "你终于来了。", "startMs": 0, "endMs": 6000}],
            }
        },
    }

    manifest = await provider.compose(project)
    artifacts = manifest["artifacts"]
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(artifacts["video.mp4"])
    probe = await asyncio.to_thread(
        subprocess.run,
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,width,height,r_frame_rate:format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(probe.stdout)
    video_stream = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
    audio_stream = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")

    assert manifest["files"] == ["video.mp4", "cover.jpg", "subtitles.srt"]
    assert video_stream == {
        "codec_name": "h264",
        "codec_type": "video",
        "width": 1080,
        "height": 1920,
        "r_frame_rate": "30/1",
    }
    assert audio_stream["codec_name"] == "aac"
    assert 5.95 <= float(metadata["format"]["duration"]) <= 6.05
    assert artifacts["cover.jpg"].startswith(b"\xff\xd8\xff")
    assert artifacts["subtitles.srt"].decode("utf-8") == (
        "1\n00:00:00,000 --> 00:00:06,000\n你终于来了。\n"
    )


async def test_composition_uploads_provider_artifacts_without_persisting_raw_bytes() -> None:
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    expected = {
        "video.mp4": b"real-mp4-bytes",
        "cover.jpg": b"real-jpeg-bytes",
        "subtitles.srt": b"real-srt-bytes",
    }

    class ArtifactComposition:
        async def compose(self, project: dict[str, object]) -> dict[str, object]:
            return {
                "files": ["video.mp4", "cover.jpg", "subtitles.srt"],
                "projectId": project["id"],
                "artifacts": expected,
            }

    class CapturingAssetStore:
        def __init__(self) -> None:
            self.uploads: dict[str, bytes] = {}

        async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
            del content_type
            self.uploads[object_key.rsplit("/", 1)[-1]] = content
            return object_key

        async def presigned_get_url(self, object_key: str, expires_in: int = 900) -> str:
            del expires_in
            return f"https://assets.test/{object_key}"

    asset_store = CapturingAssetStore()
    pipeline._composition_provider = ArtifactComposition()  # type: ignore[assignment]
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="A six-second export must upload the real provider artifacts",
            duration_sec=60,
            mode="guided",
        )
    )
    generated = await pipeline.generate_script(created["project"]["id"])
    project_id = created["project"]["id"]
    # The composition gate needs a fully generated film before it will queue.
    version = generated["project"]["version"]
    for shot in generated["script"]["shots"]:
        shot_visual = await pipeline.generate_shot_visual(
            project_id, str(shot["id"]), expected_version=version
        )
        await pipeline.adopt_video_job(project_id, shot_visual["jobId"])
        shot_audio = await pipeline.generate_shot_audio(
            project_id, str(shot["id"]), expected_version=shot_visual["projectVersion"]
        )
        version = shot_audio["projectVersion"]
    pipeline._asset_store = asset_store  # type: ignore[assignment]
    job = await pipeline.request_composition(
        project_id,
        expected_version=version,
        idempotency_key="real-artifact-upload",
    )

    completed = await pipeline.run_job(job["id"])

    assert completed["status"] == "succeeded"
    assert asset_store.uploads == expected
    assert "artifacts" not in completed["exportManifest"]


async def test_narration_only_shot_is_voiced_like_dialogue() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜的灯塔下，失踪多年的姐姐回来了",
            duration_sec=30,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    generated = await pipeline.generate_script(project_id)
    script = generated["script"]
    shots = list(script["shots"])
    shot = dict(shots[2])
    shot["dialogue"] = ""
    shot["narration"] = "雨声渐歇，姐姐的身影消失在灯影里。"
    shots[2] = shot
    script = {**script, "shots": shots}
    saved = await pipeline.update_script(
        project_id, script, expected_version=generated["project"]["version"]
    )
    shot_id = shot["id"]
    visual = await pipeline.generate_shot_visual(
        project_id, shot_id, expected_version=saved["project"]["version"]
    )
    await pipeline.adopt_video_job(project_id, visual["jobId"])
    audio = await pipeline.generate_shot_audio(
        project_id, shot_id, expected_version=visual["projectVersion"]
    )

    assert audio["asset"] is not None
    assert audio["asset"]["text"] == "雨声渐歇，姐姐的身影消失在灯影里。"
    assert audio["timeline"]["dialogue"][0]["text"] == "雨声渐歇，姐姐的身影消失在灯影里。"
