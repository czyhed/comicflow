"""End-to-end test: Generate image, then test image-to-video.

This script:
1. Generates a test image using the existing image provider
2. Uses that image as the first frame for video generation
3. Verifies the i2v API works correctly
"""

import asyncio
import os
import sys

sys.path.insert(0, "/app")

from comicflow.providers.wanx_image import BailianImageProvider
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider


async def main():
    print("=" * 70)
    print("Bailian Image-to-Video End-to-End Test")
    print("=" * 70)
    print()

    api_key = os.environ.get("BAILIAN_API_KEY")
    if not api_key:
        print("❌ BAILIAN_API_KEY not found")
        return

    print("Step 1: Generate a test image (first frame)")
    print("-" * 70)

    # Initialize image provider
    image_provider = BailianImageProvider(
        api_key=api_key,
        model="wanx2.1-t2i-plus",
        size="720*1280",
    )

    test_prompt = "一个年轻女孩站在公园里，阳光明媚，竖屏构图，电影感光影"

    try:
        print(f"Prompt: {test_prompt}")
        print("Generating image...")

        image_result = await image_provider.generate_image(
            prompt=test_prompt,
            scene="公园",
            shot={"title": "测试镜头", "order": 1},
            character_inputs=[],
        )

        image_url = image_result.get("url")
        if not image_url:
            print("❌ No image URL in result")
            print(f"Result: {image_result}")
            return

        print(f"✓ Image generated: {image_url[:80]}...")

    except Exception as e:
        print(f"❌ Image generation failed: {e}")
        import traceback
        traceback.print_exc()
        return

    print()
    print("Step 2: Test image-to-video generation")
    print("-" * 70)

    # Initialize i2v provider
    i2v_provider = BailianImageToVideoProvider(
        api_key=api_key,
        model="wan2.7-i2v",
        size="1080*1920",
        duration=5,
        timeout_seconds=300.0,
    )

    motion_prompt = "女孩微笑着挥手，镜头缓慢推进"

    try:
        print(f"First frame: {image_url[:80]}...")
        print(f"Motion prompt: {motion_prompt}")
        print("Generating video (this may take 2-5 minutes)...")

        video_url = await i2v_provider.generate_video(
            first_frame_url=image_url,
            prompt=motion_prompt,
        )

        print(f"✓ Video generated: {video_url[:80]}...")

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Video generation failed: {error_msg}")

        # Analyze the error
        if "404" in error_msg or "not found" in error_msg.lower():
            print("\n⚠ Analysis: The i2v endpoint might not exist or model name is wrong")
            print("  Try these model names:")
            print("  - wan-i2v")
            print("  - wanx-i2v")
            print("  - happyhorse-1.1-i2v")
        elif "400" in error_msg or "invalid" in error_msg.lower():
            print("\n⚠ Analysis: The request format might be incorrect")
            print("  The API might not support first_frame_image parameter")
        else:
            import traceback
            traceback.print_exc()
        return

    print()
    print("=" * 70)
    print("✓ Test completed successfully!")
    print(f"Image URL: {image_url}")
    print(f"Video URL: {video_url}")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
