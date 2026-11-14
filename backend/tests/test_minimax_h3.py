import httpx
import pytest
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from test_h3_skill_execution import valid_rewrite


class _Store:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes, str]] = []

    async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
        self.writes.append((object_key, content, content_type))
        return object_key


@pytest.mark.asyncio
async def test_minimax_submits_polls_downloads_and_persists() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/minimax/v2/video_generation":
            assert request.headers["authorization"] == "Bearer secret"
            return httpx.Response(200, json={"task_id": "h3-1"})
        if request.url.path == "/minimax/v2/query/video_generation/h3-1":
            return httpx.Response(
                200,
                json={"task": {"status": "succeeded", "content": {"url": "https://x/video.mp4"}}},
            )
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"mp4")

    store = _Store()
    provider = MinimaxH3Provider(
        api_key="secret",
        prompt_writer=H3SkillPromptWriter(valid_rewrite),
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=0,
        asset_store=store,
    )
    result = await provider.generate(
        {"id": "shot-1", "visualDescription": "雨夜车站", "durationSec": 5},
        [{"id": "c-1", "referenceImageUrl": "https://x/c.png"}],
    )
    assert calls[:2] == ["/minimax/v2/video_generation", "/minimax/v2/query/video_generation/h3-1"]
    assert result["provider"] == "minimax"
    assert result["generationMode"] == "ref2va"
    assert result["objectKey"] == store.writes[0][0]


@pytest.mark.asyncio
async def test_minimax_failed_task_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/minimax/v2/video_generation":
            return httpx.Response(200, json={"task_id": "h3-f"})
        return httpx.Response(200, json={"task": {"status": "failed"}})

    provider = MinimaxH3Provider(
        api_key="secret",
        prompt_writer=H3SkillPromptWriter(valid_rewrite),
        transport=httpx.MockTransport(handler),
        poll_interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match="VIDEO_GENERATION_FAILED"):
        await provider.generate({"id": "shot-1"}, [])


def test_minimax_builds_keyframe_request() -> None:
    provider = MinimaxH3Provider(api_key="secret")
    payload = provider._build_request(
        {
            "id": "shot-1",
            "h3Prompt": "prompt",
            "generationMode": "i2va",
            "firstFrameUrl": "https://x/first.jpg",
            "durationSec": 8,
        },
        [],
    )
    assert payload["ratio"] == "9:16"
    assert payload["content"][0]["type"] == "text"
    assert payload["content"][1]["role"] == "first_frame"


def test_minimax_defaults_to_768p_resolution() -> None:
    provider = MinimaxH3Provider(api_key="secret")
    payload = provider._build_request(
        {
            "id": "shot-1",
            "h3Prompt": "prompt",
            "durationSec": 5,
        },
        [],
    )
    assert payload["resolution"] == "768P"


def test_minimax_h3_accepts_configured_1080p_resolution() -> None:
    provider = MinimaxH3Provider(api_key="secret", model="MiniMax-H3", resolution="1080P")
    payload = provider._build_request(
        {
            "id": "shot-1",
            "h3Prompt": "prompt",
            "durationSec": 5,
        },
        [],
    )
    assert payload["resolution"] == "1080P"
