import httpx
import pytest
from comicflow.providers.video_synthesis import BailianVideoProvider


class _CapturingStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes, str]] = []

    async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
        self.writes.append((object_key, content, content_type))
        return object_key


def _handler(request: httpx.Request, polled: list[int]) -> httpx.Response:
    path = request.url.path
    if path.endswith("/video-generation/video-synthesis"):
        return httpx.Response(200, json={"output": {"task_id": "vid-1", "task_status": "PENDING"}})
    if path.endswith("/tasks/vid-1"):
        polled[0] += 1
        if polled[0] < 2:
            return httpx.Response(200, json={"output": {"task_status": "RUNNING"}})
        return httpx.Response(
            200,
            json={"output": {"task_status": "SUCCEEDED", "video_url": "https://video.test/m.mp4"}},
        )
    return httpx.Response(200, content=b"fakemp4content")


@pytest.mark.asyncio
async def test_video_provider_submits_polls_and_persists() -> None:
    polled: list[int] = [0]
    store = _CapturingStore()
    provider = BailianVideoProvider(
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        transport=httpx.MockTransport(lambda request: _handler(request, polled)),  # type: ignore[arg-type]
        asset_store=store,  # type: ignore[arg-type]
        poll_interval_seconds=0,
    )
    result = await provider.generate("雨夜灯塔，姐姐回头")

    assert polled[0] >= 2
    assert result["provider"] == "wanx"
    assert result["modelVersion"] == "wan2.2-t2v-plus"
    assert result["durationSec"] == 5
    assert result["taskId"] == "vid-1"
    assert store.writes and store.writes[0][2] == "video/mp4"
    assert result["objectKey"] == store.writes[0][0]


@pytest.mark.asyncio
async def test_video_provider_reports_failed_task() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        if _request.url.path.endswith("/video-generation/video-synthesis"):
            pending = {"output": {"task_id": "vid-f", "task_status": "PENDING"}}
            return httpx.Response(200, json=pending)
        return httpx.Response(200, json={"output": {"task_status": "FAILED"}})

    provider = BailianVideoProvider(
        api_key="secret",
        base_url="https://dashscope.aliyuncs.com/api/v1",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        poll_interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match="PROVIDER_GENERATION_FAILED"):
        await provider.generate("any prompt")
