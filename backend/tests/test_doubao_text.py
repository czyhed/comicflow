from __future__ import annotations

import json

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.doubao_text import DoubaoTextProvider


def test_doubao_provider_uses_ark_defaults() -> None:
    provider = DoubaoTextProvider(api_key="offline")

    assert provider._base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert provider._model == "Doubao-Seed-2.1-turbo"


def test_runtime_can_select_doubao_from_environment() -> None:
    from comicflow.providers.config import ProviderConfig, ProviderMode, select_provider_mode

    config = ProviderConfig.from_env({
        "PROVIDER_MODE": "real",
        "PROVIDER_EVALUATION_GATE": "passed",
        "TEXT_PROVIDER_PROVIDER": "doubao",
        "DOUBAO_API_KEY": "ark-key",
    })

    assert config.text_provider == "doubao"
    assert config.text_api_key == "ark-key"
    assert config.text_base_url == "https://ark.cn-beijing.volces.com/api/v3"
    assert config.mode is ProviderMode.REAL
    assert select_provider_mode(config) is ProviderMode.REAL


@pytest.mark.asyncio
async def test_doubao_provider_uses_openai_compatible_chat_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path == "/api/v3/chat/completions"
        assert request.headers["authorization"] == "Bearer ark-key"
        body = json.loads(request.content)
        assert body["model"] == "ep-test"
        return httpx.Response(
            200,
            json={"model": "ep-test", "choices": [{"message": {"content": "pong"}}]},
        )

    provider = DoubaoTextProvider(
        api_key="ark-key",
        model="ep-test",
        transport=httpx.MockTransport(handler),
    )

    assert await provider.check_connectivity() == "ep-test"
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_text_profile_constructs_doubao_adapter_without_model_call() -> None:
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/provider-config/profiles/text/production",
            json={
                "provider": "doubao",
                "baseUrl": "https://ark.cn-beijing.volces.com/api/v3",
                "model": "ep-test",
                "timeoutMs": 120000,
                "enabled": True,
                "apiKey": "ark-key",
            },
        )

    assert response.status_code == 200, response.text
    assert isinstance(runtime.pipeline._text_provider, DoubaoTextProvider)
    assert runtime.provider_config_store.get_text()["provider"] == "doubao"
    assert "ark-key" not in response.text
