from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from comicflow.domain.models import JsonObject

_SUBMIT = "/services/aigc/video-generation/video-synthesis"


class BailianVideoProvider:
    """Real Bailian (DashScope) wan text-to-video via the async video-synthesis task.

    Submits a vertical motion prompt per shot, polls until the task succeeds, then
    downloads the MP4 and persists it via the asset store. Used to validate and
    drive the per-shot motion slice before final pipeline wiring.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        model: str = "wan2.2-t2v-plus",
        size: str = "1080*1920",
        duration: int = 5,
        timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 6.0,
        transport: httpx.AsyncBaseTransport | None = None,
        asset_store: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._size = size
        self._duration = duration
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._transport = transport
        self._asset_store = asset_store

    async def generate(self, prompt: str) -> JsonObject:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-Async": "enable",
        }
        payload = {
            "model": self._model,
            "input": {"prompt": prompt},
            "parameters": {
                "size": self._size,
                "duration": self._duration,
                "prompt_extend": False,
                "watermark": False,
            },
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            try:
                response = await client.post(_SUBMIT, json=payload)
                response.raise_for_status()
                body = response.json()
            except httpx.TimeoutException as error:
                raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPError as error:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error
            except (ValueError, TypeError) as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

            task_id = str((body.get("output") or {}).get("task_id", ""))
            if not task_id:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            url = await self._poll(client, task_id)
            try:
                video = await client.get(url)
                video.raise_for_status()
            except httpx.TimeoutException as error:
                raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPError as error:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error

        asset: JsonObject = {
            "taskId": task_id,
            "durationSec": self._duration,
            "size": self._size,
            "provider": "wanx",
            "modelVersion": self._model,
            "sourceUrl": url,
            "bytes": len(video.content),
        }
        if self._asset_store is not None and video.content:
            object_key = f"motion/{os.urandom(4).hex()}.mp4"
            await self._asset_store.put_bytes(
                object_key=object_key,
                content=video.content,
                content_type="video/mp4",
            )
            asset["objectKey"] = object_key
        return asset

    async def _poll(self, client: httpx.AsyncClient, task_id: str) -> str:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                response = await client.get(f"/tasks/{task_id}")
                response.raise_for_status()
                output = (response.json() or {}).get("output") or {}
            except httpx.TimeoutException as error:
                raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPError as error:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error
            status = str(output.get("task_status", ""))
            if status == "SUCCEEDED":
                url = output.get("video_url")
                if isinstance(url, str) and url:
                    return url
                results = output.get("results") or []
                if results and isinstance(results[0], dict):
                    nested = results[0].get("url")
                    if isinstance(nested, str) and nested:
                        return nested
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            if status in ("FAILED", "CANCELED"):
                raise RuntimeError("PROVIDER_GENERATION_FAILED")
            await asyncio.sleep(self._poll_interval)
        raise RuntimeError("PROVIDER_TIMEOUT")
