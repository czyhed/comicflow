from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

import httpx

from comicflow.domain.models import JsonObject


class TtsHttpProvider:
    """Real Bailian (DashScope) Qwen-TTS via the multimodal generation endpoint.

    Non-streaming request returns ``output.audio.url`` (valid ~24h); the audio is
    downloaded and probed (RIFF wav header, else ffprobe) for real duration/sample
    rate. When an asset store is provided the bytes are persisted and ``objectKey``
    is returned; the provider never stores raw audio bytes in project state.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        model: str = "qwen3-tts-flash",
        voice: str = "Cherry",
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
        asset_store: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._voice = voice
        self._timeout = timeout_seconds
        self._transport = transport
        self._asset_store = asset_store

    async def generate(self, shot_id: str, speaker_id: str, text: str) -> JsonObject:
        text = str(text or "").strip()
        if not text:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        payload = {
            "model": self._model,
            "input": {
                "text": text,
                "voice": self._voice,
                "language_type": "Chinese",
            },
        }
        source_url = ""
        audio = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout,
                    transport=self._transport,
                ) as client:
                    response = await client.post(
                        "/services/aigc/multimodal-generation/generation",
                        json=payload,
                    )
                    response.raise_for_status()
                    body = response.json()
                    source_url = self._extract_audio_url(body)
                    audio_response = await client.get(source_url)
                    audio_response.raise_for_status()
                    audio = audio_response
                break
            except httpx.TimeoutException as error:
                if attempt >= 2:
                    raise RuntimeError("PROVIDER_TIMEOUT") from error
                await asyncio.sleep(0.6 * (attempt + 1))
            except httpx.ConnectError as error:
                # DNS/connect hiccups (container resolver) are transient: retry.
                if attempt >= 2:
                    raise RuntimeError("PROVIDER_HTTP_ERROR") from error
                await asyncio.sleep(0.6 * (attempt + 1))
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                code = ('PROVIDER_AUTH_FAILED' if status in (401, 403) else
                        'PROVIDER_RATE_LIMITED' if status == 429 else
                        'PROVIDER_REQUEST_INVALID' if status < 500 else 'PROVIDER_HTTP_ERROR')
                raise RuntimeError(code) from error
            except httpx.HTTPError as error:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error
            except (ValueError, TypeError) as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        if audio is None:
            raise RuntimeError("PROVIDER_HTTP_ERROR")
        content = audio.content
        duration_ms, sample_rate = await asyncio.to_thread(probe_audio, content)
        if duration_ms <= 0 or sample_rate <= 0:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")

        asset: JsonObject = {
            "id": f"audio-{shot_id}",
            "shotId": shot_id,
            "speakerId": speaker_id,
            "text": text,
            "durationMs": int(duration_ms),
            "sampleRate": int(sample_rate),
            "voice": self._voice,
            "provider": "bailian",
            "modelVersion": self._model,
            "sourceUrl": source_url,
        }
        if self._asset_store is not None and content:
            object_key = f"audio/{shot_id}/{os.urandom(4).hex()}.wav"
            await self._asset_store.put_bytes(
                object_key=object_key,
                content=content,
                content_type="audio/wav",
            )
            asset["objectKey"] = object_key
            asset["sizeBytes"] = len(content)
        return asset

    @staticmethod
    def _extract_audio_url(body: Any) -> str:
        if not isinstance(body, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        output = body.get("output")
        if not isinstance(output, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        audio = output.get("audio")
        if not isinstance(audio, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        url = audio.get("url")
        if not isinstance(url, str) or not url:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return url


def probe_audio(content: bytes) -> tuple[float, int]:
    """Return (duration_ms, sample_rate); ffprobe is authoritative (DashScope wav
    payloads may use RF64 oversized headers that break the naive wave reader)."""
    ffmpeg_result = _probe_with_ffprobe(content)
    if ffmpeg_result != (0.0, 0):
        return ffmpeg_result
    try:
        with wave.open(io.BytesIO(content), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate()
            if rate > 0:
                return round(frames / rate * 1000), int(rate)
    except (wave.Error, EOFError, ValueError, OSError):
        pass
    return 0.0, 0


def _probe_with_ffprobe(content: bytes) -> tuple[float, int]:
    if shutil.which("ffprobe") is None:
        return 0.0, 0
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as handle:
        handle.write(content)
        path = handle.name
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=duration,sample_rate",
                "-show_entries", "format=duration",
                "-of", "json", path,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return 0.0, 0
        data = json.loads(result.stdout)
        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        seconds = float(fmt.get("duration") or 0)
        if streams:
            seconds = float(streams[0].get("duration") or seconds)
        rate = int(streams[0].get("sample_rate") or 0) if streams else 0
        return round(seconds * 1000), rate
    except (ValueError, KeyError, OSError, json.JSONDecodeError):
        return 0.0, 0
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


class LipSyncHttpProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    async def generate(
        self, shot_id: str, audio_asset: JsonObject, dialogue: JsonObject
    ) -> JsonObject:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/audio/lipsync",
                    json={"audioAssetId": audio_asset["id"], "dialogue": dialogue},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as error:
            raise RuntimeError("PROVIDER_TIMEOUT") from error
        except httpx.HTTPError as error:
            raise RuntimeError("PROVIDER_HTTP_ERROR") from error
        except (ValueError, TypeError) as error:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

        if not isinstance(body, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        source_url = body.get("assetUrl")
        start_ms = body.get("startMs")
        end_ms = body.get("endMs")
        if (
            not isinstance(source_url, str)
            or not isinstance(start_ms, int)
            or not isinstance(end_ms, int)
        ):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return {
            "id": f"lipsync-{shot_id}",
            "shotId": shot_id,
            "audioAssetId": audio_asset["id"],
            "startMs": start_ms,
            "endMs": end_ms,
            "sourceUrl": source_url,
            "provider": "real",
        }
