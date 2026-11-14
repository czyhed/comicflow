from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def test_provider_config_is_saved_and_key_is_redacted() -> None:
    runtime = create_memory_runtime()
    app = create_app(runtime)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await client.put(
            "/api/provider-config/text",
            json={
                "provider": "openai-compatible",
                "baseUrl": "https://provider.test/v1",
                "model": "script-v1",
                "timeoutMs": 30000,
                "enabled": True,
                "apiKey": "secret-key",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["configured"] is True
        assert "secret-key" not in saved.text

        read = await client.get("/api/provider-config")
        assert read.status_code == 200
        assert read.json()["text"]["apiKeyMasked"] == "********"
        assert "apiKey" not in read.json()["text"]


async def test_provider_config_can_be_deleted() -> None:
    runtime = create_memory_runtime()
    app = create_app(runtime)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.put(
            "/api/provider-config/text",
            json={
                "provider": "custom",
                "baseUrl": "https://provider.test",
                "model": "v1",
                "apiKey": "key",
                "enabled": True,
            },
        )
        deleted = await client.delete("/api/provider-config/text")
        assert deleted.status_code == 204
        assert (await client.get("/api/provider-config")).json()["text"]["configured"] is False
