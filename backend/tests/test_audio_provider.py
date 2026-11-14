import io
import wave

import httpx
import pytest
from comicflow.providers.audio import LipSyncHttpProvider, TtsHttpProvider

AUDIO_URL = "https://audio.test/cdn/a.wav"


def _wav_bytes(frames: int = 12_000, rate: int = 24_000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()


def _handler_ok(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/services/aigc/multimodal-generation/generation":
        return httpx.Response(200, json={"output": {"audio": {"url": AUDIO_URL}}})
    assert request.url.path == "/cdn/a.wav"
    return httpx.Response(200, content=_wav_bytes())


@pytest.mark.asyncio
async def test_tts_provider_returns_probed_metadata_without_audio_bytes() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/services/aigc/multimodal-generation/generation":
            captured["payload"] = request.read().decode("utf-8")
            return httpx.Response(200, json={"output": {"audio": {"url": AUDIO_URL}}})
        return httpx.Response(200, content=_wav_bytes())

    provider = TtsHttpProvider(
        api_key="secret",
        base_url="https://audio.test",
        voice="Cherry",
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate("shot-1", "speaker-1", "你好")

    import json
    payload = json.loads(str(captured["payload"]))
    assert payload["model"] == "qwen3-tts-flash"
    assert payload["input"]["text"] == "你好"
    assert payload["input"]["voice"] == "Cherry"
    assert result["id"] == "audio-shot-1"
    assert result["shotId"] == "shot-1"
    assert result["durationMs"] == 500  # 12000 frames / 24000 Hz
    assert result["sampleRate"] == 24000
    assert result["voice"] == "Cherry"
    assert result["provider"] == "bailian"
    assert result["sourceUrl"] == AUDIO_URL
    assert "bytes" not in result
    assert "objectKey" not in result


@pytest.mark.asyncio
async def test_tts_provider_uploads_to_asset_store_when_available() -> None:
    class CapturingStore:
        def __init__(self) -> None:
            self.writes: list[tuple[str, bytes, str]] = []

        async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str:
            self.writes.append((object_key, content, content_type))
            return object_key

    store = CapturingStore()
    provider = TtsHttpProvider(
        api_key="secret",
        base_url="https://audio.test",
        transport=httpx.MockTransport(_handler_ok),
        asset_store=store,  # type: ignore[arg-type]
    )
    result = await provider.generate("shot-1", "speaker-1", "你好")
    assert store.writes and store.writes[0][2] == "audio/wav"
    assert result["objectKey"] == store.writes[0][0]
    assert result["sizeBytes"] == len(store.writes[0][1])


@pytest.mark.asyncio
async def test_tts_provider_classifies_invalid_response() -> None:
    provider = TtsHttpProvider(
        api_key="secret",
        base_url="https://audio.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"output": {}})),
    )
    with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
        await provider.generate("shot-1", "speaker-1", "你好")


@pytest.mark.asyncio
async def test_tts_provider_classifies_http_error() -> None:
    provider = TtsHttpProvider(
        api_key="secret",
        base_url="https://audio.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    with pytest.raises(RuntimeError, match="PROVIDER_HTTP_ERROR"):
        await provider.generate("shot-1", "speaker-1", "你好")


@pytest.mark.asyncio
async def test_lipsync_provider_returns_asset_timing_metadata() -> None:
    provider = LipSyncHttpProvider(
        api_key="secret",
        base_url="https://audio.test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"assetUrl": "https://cdn.test/lipsync.json", "startMs": 0, "endMs": 1560},
            )
        ),
    )
    result = await provider.generate(
        "shot-1",
        {"id": "audio-shot-1", "durationMs": 1560},
        {"startMs": 0, "endMs": 1560},
    )
    assert result == {
        "id": "lipsync-shot-1",
        "shotId": "shot-1",
        "audioAssetId": "audio-shot-1",
        "startMs": 0,
        "endMs": 1560,
        "sourceUrl": "https://cdn.test/lipsync.json",
        "provider": "real",
    }


class _FlakyTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport, failures: int) -> None:
        self.inner = inner
        self.failures = failures
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.failures > 0:
            self.failures -= 1
            raise httpx.ConnectError("temporary dns failure", request=request)
        return await self.inner.handle_async_request(request)


@pytest.mark.asyncio
async def test_tts_provider_retries_transient_connect_errors() -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path == "/services/aigc/multimodal-generation/generation":
            posts += 1
            return httpx.Response(200, json={"output": {"audio": {"url": AUDIO_URL}}})
        return httpx.Response(200, content=_wav_bytes())

    flaky = _FlakyTransport(httpx.MockTransport(handler), failures=2)
    provider = TtsHttpProvider(
        api_key="secret",
        base_url="https://audio.test",
        transport=flaky,  # type: ignore[arg-type]
    )
    result = await provider.generate("shot-1", "speaker-1", "你好")
    # 2 DNS failures, then the successful POST and its audio GET.
    assert flaky.attempts == 4
    assert posts == 1  # handler only sees the successful attempt
    assert result["durationMs"] == 500
