import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from comicflow.providers.wanx_image import BailianImageProvider


@pytest.mark.parametrize(
    "capability,provider,expected",
    [
        ("image", "bailian-image", BailianImageProvider),
        ("video", "compshare-h3", MinimaxH3Provider),
    ],
)
async def test_media_config_saves_masks_and_switches_without_network(
    capability, provider, expected
):
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        profile = {
            "provider": provider,
            "baseUrl": "https://provider.test",
            "model": "model",
            "enabled": True,
            "apiKey": "secret-for-test",
            "timeoutMs": 600000,
        }
        saved = await client.put("/api/provider-config/media/" + capability, json=profile)
        assert saved.status_code == 200
        assert "secret-for-test" not in saved.text
        assert "apiKey" not in saved.json()
        view = (await client.get("/api/provider-config")).json()
        assert view[capability]["configured"] is True
        assert view["h3Prompt"]["required"] is True
        assert "secret-for-test" not in str(view)
        actual = (
            runtime.pipeline._reference_image_provider
            if capability == "image"
            else runtime.pipeline._dynamic_visual_provider
        )
        assert isinstance(actual, expected)
        profile.pop("apiKey")
        profile["model"] = "updated-model"
        assert (
            await client.put("/api/provider-config/media/" + capability, json=profile)
        ).status_code == 200
        assert runtime.provider_config_store.get_media(capability)["apiKey"] == "secret-for-test"
        invalid = {
            **profile,
            "provider": "compshare-h3" if capability == "image" else "bailian-image",
        }
        assert (
            await client.put("/api/provider-config/media/" + capability, json=invalid)
        ).status_code == 400
        assert runtime.provider_config_store.get_media(capability)["model"] == "updated-model"
        assert (await client.delete("/api/provider-config/media/" + capability)).status_code == 204
        assert not (await client.get("/api/provider-config")).json()[capability]["configured"]


async def test_text_changes_rebind_h3_skill_and_do_not_leak_secret():
    runtime = create_memory_runtime()
    video = MinimaxH3Provider(api_key="video-key")
    runtime.pipeline.set_video_provider(video)
    assert video._prompt_writer is None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/provider-config/text",
            json={
                "provider": "bailian",
                "baseUrl": "https://text.test/v1",
                "model": "writer-model",
                "enabled": True,
                "apiKey": "text-key",
                "timeoutMs": 30000,
            },
        )
        assert response.status_code == 200
        assert "text-key" not in response.text
        assert isinstance(runtime.pipeline._text_provider, BailianTextProvider)
        assert video._prompt_writer is not None
        await client.delete("/api/provider-config/text")
        assert video._prompt_writer is None


async def test_h3_resolution_profile_reaches_provider_and_rejects_720p():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        profile = {
            "provider": "compshare-h3",
            "baseUrl": "https://h3.test",
            "model": "MiniMax-H3",
            "enabled": True,
            "apiKey": "offline",
            "timeoutMs": 60000,
            "resolution": "768P",
        }
        response = await client.put("/api/provider-config/media/video", json=profile)
        assert response.status_code == 200, response.text
        provider = runtime.pipeline._dynamic_visual_provider
        assert isinstance(provider, MinimaxH3Provider)
        assert provider._resolution == "768P"
        assert provider._build_request(
            {"id": "s1", "h3Prompt": "prompt", "durationSec": 5}, []
        )["resolution"] == "768P"

        refused = await client.put(
            "/api/provider-config/media/video",
            json={**profile, "resolution": "720P"},
        )
        assert refused.status_code == 400
        assert runtime.pipeline._dynamic_visual_provider._resolution == "768P"
