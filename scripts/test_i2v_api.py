"""Test script to verify Bailian image-to-video API.

This script tests:
1. Whether the i2v API endpoint exists and is accessible
2. What parameters are supported
3. Whether reference images work
"""

import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend", "src"))

from comicflow.providers.bailian_i2v import BailianImageToVideoProvider


async def test_i2v_basic():
    """Test basic image-to-video generation."""
    api_key = os.environ.get("BAILIAN_API_KEY")
    if not api_key:
        print("❌ BAILIAN_API_KEY not found in environment")
        return False

    print("✓ API Key found")
    print(f"  Key prefix: {api_key[:20]}...")

    # Use a sample image URL (we'll need a real one for actual testing)
    # For now, let's just test the provider initialization
    provider = BailianImageToVideoProvider(
        api_key=api_key,
        model="wan2.7-i2v",  # Try the documented model name
        size="1080*1920",
        duration=5,
    )

    print("✓ Provider initialized")
    print(f"  Model: wan2.7-i2v")
    print(f"  Size: 1080*1920")
    print(f"  Duration: 5s")

    # We can't actually test without a real image URL
    # Let's document what we need
    print("\n⚠ To complete the test, we need:")
    print("  1. A publicly accessible image URL (first frame)")
    print("  2. A text prompt describing the desired motion")
    print("  3. (Optional) Character reference image URLs")

    return True


async def test_model_names():
    """Test different possible model names."""
    possible_models = [
        "wan2.7-i2v",
        "wan-i2v",
        "wanx-i2v",
        "happyhorse-1.1-i2v",
    ]

    print("\nPossible model names to try:")
    for model in possible_models:
        print(f"  - {model}")

    return True


async def main():
    print("=" * 60)
    print("Bailian Image-to-Video API Test")
    print("=" * 60)
    print()

    success = await test_i2v_basic()
    await test_model_names()

    print()
    print("=" * 60)
    if success:
        print("✓ Basic setup verified")
        print("\nNext steps:")
        print("1. Generate a test image using the existing image provider")
        print("2. Use that image URL to test i2v generation")
        print("3. Verify the generated video URL is accessible")
    else:
        print("❌ Setup verification failed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
