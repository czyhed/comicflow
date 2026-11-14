import httpx
import pytest
from comicflow.providers.async_visual import AsyncVisualProvider


def _provider(handler, **kwargs) -> AsyncVisualProvider:
    return AsyncVisualProvider(
        api_key="test-key",
        base_url="https://visual.test",
        model="visual-v1",
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_visual_provider_polls_until_completed_and_returns_metadata() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.method == "POST":
            return httpx.Response(202, json={"taskId": "task-1"})
        if len(calls) == 2:
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "output": {"url": "https://cdn.test/video.mp4", "durationMs": 6000},
            },
        )

    result = await _provider(handler, max_poll_attempts=3).generate(
        {"id": "shot-1", "durationSec": 6, "visualDescription": "雨夜车站"}, []
    )

    assert calls == ["/tasks", "/tasks/task-1", "/tasks/task-1"]
    assert result["mediaType"] == "video"
    assert result["durationMs"] == 6000
    assert result["provider"] == "real"
    assert result["modelVersion"] == "visual-v1"
    assert result["requestReference"] == "task-1"
    assert result["sourceUrl"] == "https://cdn.test/video.mp4"
    assert result["fallback"] is False


@pytest.mark.asyncio
async def test_visual_provider_classifies_poll_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"taskId": "task-timeout"})
        return httpx.Response(200, json={"status": "running"})

    with pytest.raises(RuntimeError, match="PROVIDER_TIMEOUT"):
        await _provider(handler, max_poll_attempts=2).generate(
            {"id": "shot-1", "durationSec": 6, "visualDescription": "雨夜车站"}, []
        )


@pytest.mark.asyncio
async def test_visual_provider_classifies_terminal_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"taskId": "task-failed"})
        return httpx.Response(200, json={"status": "failed", "error": "content rejected"})

    with pytest.raises(RuntimeError, match="PROVIDER_GENERATION_FAILED"):
        await _provider(handler).generate(
            {"id": "shot-1", "durationSec": 6, "visualDescription": "雨夜车站"}, []
        )


@pytest.mark.asyncio
async def test_visual_provider_returns_explicit_fallback_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "unavailable"})

    result = await _provider(
        handler,
        fallback_metadata={"mediaType": "image", "objectKey": "fallback/shot-1.png"},
    ).generate({"id": "shot-1", "durationSec": 6}, [])

    assert result["fallback"] is True
    assert result["provider"] == "fallback"
    assert result["mediaType"] == "image"
    assert result["objectKey"] == "fallback/shot-1.png"
