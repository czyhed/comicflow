"""Read-only image provider routing facts exposed by the API."""

import httpx
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime


async def _save_image_profile(client: httpx.AsyncClient, provider: str, model: str, **extra):
    payload = {
        "provider": provider,
        "baseUrl": "https://provider.test",
        "model": model,
        "enabled": True,
        "apiKey": "offline-key",
        "timeoutMs": 60000,
        **extra,
    }
    response = await client.put("/api/provider-config/media/image", json=payload)
    assert response.status_code == 200


async def test_provider_config_reports_bailian_model_protocol_without_network():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        await _save_image_profile(client, "bailian-image", "wan2.6-image")

        response = await client.get("/api/provider-config")

    assert response.status_code == 200
    routing = response.json()["runtime"]
    assert routing["imageAdapter"] == "BailianImageProvider"
    assert routing["imageModel"] == "wan2.6-image"
    assert routing["imageProtocol"] == "wan26-image"


async def test_provider_config_reports_openai_image_adapter_without_network():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        await _save_image_profile(client, "openai-image", "image-2.5")

        response = await client.get("/api/provider-config")

    assert response.status_code == 200
    routing = response.json()["runtime"]
    assert routing["imageAdapter"] == "OpenAIImageProvider"
    assert routing["imageModel"] == "image-2.5"
    assert routing["imageProtocol"] == "chat-completions-base64"
