"""Minimal real H3 integration verification script.

This script creates a minimal test project and verifies the complete data flow:
1. Character reference image generation
2. Scene background image generation
3. First shot video generation (using scene background as first frame)
4. Last frame extraction
5. Second shot video generation (using first shot's last frame as first frame)
6. FFmpeg video composition
7. Export to desktop for manual review

WARNING: This script will consume MiniMax API credits. Only run with explicit user permission.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from comicflow.domain.models import Actor, CreateProject
from comicflow.infrastructure.memory import (
    InMemoryCharacterRepository,
    InMemoryGenerationStateStore,
    InMemoryProjectRepository,
    Runtime,
)
from comicflow.production.pipeline import ProductionPipeline
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.ffmpeg import FfmpegCompositionProvider
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from comicflow.providers.mock import MockTextProvider
from comicflow.providers.mock_media import (
    MockLipSyncProvider,
    MockModerationProvider,
    MockTtsProvider,
)
from comicflow.providers.s3 import create_optional_asset_store
from comicflow.providers.wanx_image import BailianImageProvider


def create_real_h3_runtime() -> Runtime:
    """Create runtime with real MiniMax H3 provider for verification."""
    import os

    # Get API keys from environment
    minimax_api_key = os.getenv("MINIMAX_API_KEY")
    if not minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY is required in .env")

    bailian_api_key = os.getenv("BAILIAN_API_KEY")
    if not bailian_api_key:
        raise RuntimeError("BAILIAN_API_KEY is required for image generation")

    # Create asset store
    asset_store = create_optional_asset_store()
    if asset_store is None:
        raise RuntimeError("Asset store (MinIO) is required for H3 verification")

    # Configure MiniMax H3 provider
    minimax_base_url = os.getenv("MINIMAX_BASE_URL", "https://cp.compshare.cn")
    minimax_model = os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-H3")
    minimax_submit_path = os.getenv("MINIMAX_SUBMIT_PATH", "/minimax/v2/video_generation")
    minimax_query_path = os.getenv(
        "MINIMAX_QUERY_PATH", "/minimax/v2/query/video_generation/{task_id}"
    )

    h3_provider = MinimaxH3Provider(
        api_key=minimax_api_key,
        base_url=minimax_base_url,
        model=minimax_model,
        submit_path=minimax_submit_path,
        query_path=minimax_query_path,
        timeout_seconds=600.0,
        poll_interval_seconds=5.0,
        asset_store=asset_store,
    )

    # Use Bailian for text and image generation
    bailian_base_url = os.getenv("BAILIAN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")

    text_provider = BailianTextProvider(
        api_key=bailian_api_key, base_url=bailian_base_url, timeout_seconds=120.0
    )

    image_provider = BailianImageProvider(
        api_key=bailian_api_key,
        base_url=bailian_base_url,
        model="wanx2.1-t2i-plus",
        size="720*1280",
        asset_store=asset_store,
    )

    # Use FFmpeg for composition
    composition_provider = FfmpegCompositionProvider(asset_store=asset_store)

    # Use Mock for TTS and LipSync (not critical for H3 verification)
    tts_provider = MockTtsProvider()
    lip_sync_provider = MockLipSyncProvider()
    moderation_provider = MockModerationProvider()

    generation_state_store = InMemoryGenerationStateStore()

    return Runtime(
        pipeline=ProductionPipeline(
            repository=InMemoryProjectRepository(),
            character_repository=InMemoryCharacterRepository(),
            text_provider=text_provider,
            dynamic_visual_provider=h3_provider,  # Use real MiniMax H3
            tts_provider=tts_provider,
            lip_sync_provider=lip_sync_provider,
            composition_provider=composition_provider,
            moderation_provider=moderation_provider,
            generation_state_store=generation_state_store,
            asset_store=asset_store,  # Pass asset store for frame extraction
        ),
        provider_config_store=None,  # Not needed for this test
        generation_state_store=generation_state_store,
    )


async def verify_h3_integration():
    """Run minimal H3 integration verification."""
    print("=" * 80)
    print("MiniMax H3 Integration Verification")
    print("=" * 80)
    print()
    print("WARNING: This will consume real API credits!")
    print()

    # Create runtime with real providers
    runtime = create_real_h3_runtime()
    pipeline = runtime.pipeline

    # Step 1: Create test project
    print("Step 1: Creating test project...")
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="一个简短的测试故事。小明在公园里散步，看到了一只可爱的小猫。他决定和小猫一起玩耍。",
            duration_sec=30,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    print(f"[OK] Project created: {project_id}")
    print()

    # Step 2: Generate script
    print("Step 2: Generating script...")
    await pipeline.generate_script(project_id)
    project = (await pipeline._repository.get(project_id)).project
    version = project["version"]
    print(f"[OK] Script generated (version {version})")
    script = project["script"]
    print(f"   - Scenes: {len(script.get('scenes', []))}")
    print(f"   - Shots: {len(script.get('shots', []))}")
    print()

    # Step 3: Confirm script (generates character reference and scene background)
    print("Step 3: Confirming script (generating reference assets)...")
    await pipeline.confirm_script(project_id, expected_version=version)
    project = (await pipeline._repository.get(project_id)).project
    print("[OK] Script confirmed")

    # Check character references
    character_ids = set()
    for shot in script.get("shots", []):
        for char_id in shot.get("characterIds", []):
            character_ids.add(char_id)

    if character_ids:
        print(f"   - Character references generated: {len(character_ids)}")
        for char_id in character_ids:
            character = await pipeline._character_repository.get(char_id)
            if character and character.get("referenceImageUrl"):
                print(f"     [+] {character['name']}: {character['referenceImageUrl'][:60]}...")

    # Check scene backgrounds
    scenes = script.get("scenes", [])
    if scenes:
        print(f"   - Scene backgrounds generated: {len(scenes)}")
        for scene in scenes:
            if scene.get("backgroundImageUrl"):
                print(f"     [+] {scene.get('title', 'Scene')}: {scene['backgroundImageUrl'][:60]}...")
    print()

    # Step 4: Generate visual assets for first 2 shots
    print("Step 4: Generating visual assets (videos with cascade)...")
    shots = script["shots"][:2]  # Only first 2 shots for minimal test

    for i, shot in enumerate(shots):
        shot_id = shot["id"]
        project = (await pipeline._repository.get(project_id)).project
        version = project["version"]

        print(f"   Shot {i+1}/{len(shots)}: {shot.get('title', shot_id)}")
        try:
            result = await pipeline.generate_shot_visual(
                project_id, shot_id, expected_version=version
            )
            asset = result["asset"]
            print(f"     [OK] Visual generated")
            print(f"        - Media type: {asset.get('mediaType')}")
            print(f"        - Object key: {asset.get('objectKey')}")
            if asset.get("cascadeFromShotId"):
                print(f"        - Cascaded from: {asset['cascadeFromShotId']}")
            if asset.get("firstFrameObjectKey"):
                print(f"        - First frame: {asset['firstFrameObjectKey']}")
            if asset.get("lastFrameObjectKey"):
                print(f"        - Last frame: {asset['lastFrameObjectKey']}")
        except Exception as e:
            print(f"     [FAIL] Failed: {e}")
            raise
    print()

    # Step 5: Generate audio assets
    print("Step 5: Generating audio assets...")
    for i, shot in enumerate(shots):
        shot_id = shot["id"]
        project = (await pipeline._repository.get(project_id)).project
        version = project["version"]

        print(f"   Shot {i+1}/{len(shots)}: {shot.get('title', shot_id)}")
        try:
            result = await pipeline.generate_shot_audio(
                project_id, shot_id, expected_version=version
            )
            if result.get("asset"):
                print(f"     [OK] Audio generated")
            else:
                print(f"     [WARN]  No audio (silent shot)")
        except Exception as e:
            print(f"     [FAIL] Failed: {e}")
            raise
    print()

    # Step 6: Request composition
    print("Step 6: Requesting video composition...")
    project = (await pipeline._repository.get(project_id)).project
    version = project["version"]

    try:
        result = await pipeline.request_composition(project_id, expected_version=version)
        job_id = result["job"]["id"]
        print(f"[OK] Composition requested: {job_id}")
    except Exception as e:
        print(f"[FAIL] Failed: {e}")
        raise
    print()

    # Step 7: Wait for composition to complete
    print("Step 7: Waiting for composition to complete...")
    max_attempts = 60  # 5 minutes max
    attempt = 0

    while attempt < max_attempts:
        await asyncio.sleep(5)
        attempt += 1

        project = (await pipeline._repository.get(project_id)).project
        jobs = project.get("jobs", [])
        job = next((j for j in jobs if j["id"] == job_id), None)

        if not job:
            print("[FAIL] Job not found")
            raise RuntimeError("Job not found")

        status = job.get("status")
        print(f"   Attempt {attempt}/{max_attempts}: {status}")

        if status == "completed":
            print("[OK] Composition completed")
            break
        elif status == "failed":
            error = job.get("error", "Unknown error")
            print(f"[FAIL] Composition failed: {error}")
            raise RuntimeError(f"Composition failed: {error}")

    if attempt >= max_attempts:
        print("[FAIL] Composition timeout")
        raise RuntimeError("Composition timeout")
    print()

    # Step 8: Export video to desktop
    print("Step 8: Exporting video to desktop...")

    # Get export manifest
    export_manifest = project.get("exportManifest")
    if not export_manifest:
        print("[FAIL] No export manifest found")
        raise RuntimeError("No export manifest")

    artifacts = export_manifest.get("artifacts", {})
    video_data = artifacts.get("video.mp4")

    if not video_data:
        print("[FAIL] No video data found")
        raise RuntimeError("No video data")

    # Save to desktop
    desktop = Path.home() / "Desktop"
    output_path = desktop / f"comicflow_h3_test_{project_id}.mp4"

    with open(output_path, "wb") as f:
        f.write(video_data)

    print(f"[OK] Video exported to: {output_path}")
    print(f"   File size: {len(video_data) / 1024 / 1024:.2f} MB")

    # Also save subtitles
    subtitle_data = artifacts.get("subtitles.srt")
    if subtitle_data:
        subtitle_path = desktop / f"comicflow_h3_test_{project_id}.srt"
        with open(subtitle_path, "wb") as f:
            f.write(subtitle_data)
        print(f"[OK] Subtitles exported to: {subtitle_path}")

    # Also save cover
    cover_data = artifacts.get("cover.jpg")
    if cover_data:
        cover_path = desktop / f"comicflow_h3_test_{project_id}_cover.jpg"
        with open(cover_path, "wb") as f:
            f.write(cover_data)
        print(f"[OK] Cover exported to: {cover_path}")

    print()
    print("=" * 80)
    print("Verification Complete!")
    print("=" * 80)
    print()
    print(f"[FILES] Output files saved to: {desktop}")
    print(f"   - Video: comicflow_h3_test_{project_id}.mp4")
    print(f"   - Subtitles: comicflow_h3_test_{project_id}.srt")
    print(f"   - Cover: comicflow_h3_test_{project_id}_cover.jpg")
    print()
    print("[OK] Please review the video to verify:")
    print("   1. Visual quality and coherence")
    print("   2. Scene continuity (first frame cascade)")
    print("   3. Audio sync with visuals")
    print("   4. Subtitle timing")
    print()


if __name__ == "__main__":
    import sys

    # Fix Windows console encoding
    if sys.platform == "win32":
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, errors="replace")

    # Load .env file
    from pathlib import Path

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    print()
    print("WARNING: This script will consume real MiniMax API credits!")
    print()
    confirmation = input("Type 'yes' to proceed with real API verification: ")

    if confirmation.lower() != "yes":
        print("Verification cancelled by user")
        exit(0)

    print()
    asyncio.run(verify_h3_integration())
