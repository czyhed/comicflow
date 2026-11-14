"""Verify H3 integration via production API.

This script uses the running production API (http://127.0.0.1:18001)
to create a test project and verify the H3 video generation flow.
"""

import asyncio
import json
import time
from pathlib import Path

import httpx


BASE_URL = "http://127.0.0.1:18001"


async def verify_h3_via_api():
    """Run H3 verification via production API."""
    print("=" * 80)
    print("MiniMax H3 Integration Verification (via API)")
    print("=" * 80)
    print()

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        # Step 1: Create project
        print("Step 1: Creating test project...")
        response = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "一个简短的测试故事。小明在雨夜的车站等车，看到一只流浪猫在雨中瑟瑟发抖。他走过去，用外套为小猫遮雨。",
                "durationSec": 30,
                "mode": "guided",
            },
        )
        response.raise_for_status()
        data = response.json()
        project_id = data["project"]["id"]
        print(f"[OK] Project created: {project_id}")
        print()

        # Step 2: Generate script
        print("Step 2: Generating script...")
        response = await client.post(f"/api/projects/{project_id}/script")
        response.raise_for_status()
        data = response.json()
        print(f"[OK] Script generated (version {data['project']['version']})")
        script = data["project"]["script"]
        print(f"   - Scenes: {len(script.get('scenes', []))}")
        print(f"   - Shots: {len(script.get('shots', []))}")
        print()

        # Wait for script generation to complete
        await asyncio.sleep(2)

        # Get updated project
        response = await client.get(f"/api/projects/{project_id}")
        response.raise_for_status()
        project = response.json()["project"]
        script = project["script"]
        version = project["version"]

        # Step 3: Confirm script
        print("Step 3: Confirming script (generating reference assets)...")
        response = await client.post(
            f"/api/projects/{project_id}/script/confirm",
            json={"expectedVersion": version},
        )
        response.raise_for_status()
        data = response.json()
        print("[OK] Script confirmed")
        print()

        # Wait for reference assets to generate
        await asyncio.sleep(5)

        # Get updated project to check references
        response = await client.get(f"/api/projects/{project_id}")
        response.raise_for_status()
        project = response.json()["project"]
        script = project["script"]
        version = project["version"]

        # Check character references
        character_ids = set()
        for shot in script.get("shots", []):
            for char_id in shot.get("characterIds", []):
                character_ids.add(char_id)

        if character_ids:
            print(f"   - Character references: {len(character_ids)} generated")
            for char_id in list(character_ids)[:3]:  # Show first 3
                response = await client.get(f"/api/characters/{char_id}")
                if response.status_code == 200:
                    character = response.json()
                    if character.get("referenceImageUrl"):
                        print(f"     [+] {character['name']}: has reference image")

        # Check scene backgrounds
        scenes = script.get("scenes", [])
        if scenes:
            bg_count = sum(1 for s in scenes if s.get("backgroundImageUrl"))
            print(f"   - Scene backgrounds: {bg_count}/{len(scenes)} generated")
        print()

        # Step 4: Generate visual assets for first 2 shots
        print("Step 4: Generating visual assets (videos with cascade)...")
        shots = script["shots"][:2]  # Only first 2 shots

        for i, shot in enumerate(shots):
            shot_id = shot["id"]
            print(f"   Shot {i+1}/{len(shots)}: {shot.get('title', shot_id)[:40]}...")

            # Get current version
            response = await client.get(f"/api/projects/{project_id}")
            response.raise_for_status()
            version = response.json()["project"]["version"]

            try:
                response = await client.post(
                    f"/api/projects/{project_id}/shots/{shot_id}/visual",
                    json={"expectedVersion": version},
                )
                response.raise_for_status()
                data = response.json()
                asset = data["asset"]

                print(f"     [OK] Visual requested")
                print(f"        - Media type: {asset.get('mediaType')}")
                print(f"        - Provider: {asset.get('provider')}")

                if asset.get("cascadeFromShotId"):
                    print(f"        - Cascaded from: {asset['cascadeFromShotId']}")

                # Wait for video generation (polling)
                print(f"     [WAIT] Polling for video generation...")
                max_attempts = 120  # 10 minutes max
                attempt = 0

                while attempt < max_attempts:
                    await asyncio.sleep(5)
                    attempt += 1

                    response = await client.get(f"/api/projects/{project_id}")
                    response.raise_for_status()
                    project = response.json()["project"]

                    # Find the asset
                    visual_assets = project.get("visualAssets", [])
                    current_asset = next(
                        (a for a in visual_assets if a["shotId"] == shot_id and a.get("valid")),
                        None,
                    )

                    if current_asset:
                        # Check if it has frames extracted
                        if current_asset.get("firstFrameObjectKey"):
                            print(f"     [OK] Video generated with frames extracted")
                            print(f"        - First frame: {current_asset.get('firstFrameObjectKey')}")
                            print(f"        - Last frame: {current_asset.get('lastFrameObjectKey')}")
                            break
                        else:
                            # Video exists but frames not extracted yet
                            if attempt % 6 == 0:  # Print every 30 seconds
                                print(f"        [{attempt * 5}s] Waiting for frame extraction...")
                    else:
                        if attempt % 6 == 0:
                            print(f"        [{attempt * 5}s] Waiting for generation...")

                if attempt >= max_attempts:
                    print(f"     [WARN] Timeout waiting for video generation")

            except httpx.HTTPStatusError as e:
                print(f"     [FAIL] HTTP {e.response.status_code}: {e.response.text[:200]}")
                raise
            except Exception as e:
                print(f"     [FAIL] {e}")
                raise

        print()
        print("=" * 80)
        print("Verification Complete!")
        print("=" * 80)
        print()
        print(f"Project ID: {project_id}")
        print(f"View in browser: http://127.0.0.1:5173/workspace/{project_id}")
        print()
        print("Next steps:")
        print("  1. Check the project in the UI")
        print("  2. Verify video quality and cascade effect")
        print("  3. Generate audio and compose if needed")
        print()


if __name__ == "__main__":
    import sys

    # Fix Windows console encoding
    if sys.platform == "win32":
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, errors="replace")

    print()
    print("WARNING: This will consume real MiniMax API credits!")
    print()
    confirmation = input("Type 'yes' to proceed: ")

    if confirmation.lower() != "yes":
        print("Verification cancelled")
        sys.exit(0)

    print()
    asyncio.run(verify_h3_via_api())
