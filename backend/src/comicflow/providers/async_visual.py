from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx

from comicflow.domain.models import JsonObject


class AsyncVisualProvider:
    """Adapter for submit/poll visual generation APIs."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_poll_attempts: int = 20,
        poll_interval_seconds: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
        fallback_metadata: Mapping[str, object] | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._max_poll_attempts = max(1, max_poll_attempts)
        self._poll_interval = max(0.0, poll_interval_seconds)
        self._transport = transport
        self._fallback = dict(fallback_metadata) if fallback_metadata is not None else None

    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject]
    ) -> JsonObject:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/tasks",
                    json={
                        "model": self._model,
                        "shotId": shot["id"],
                        "prompt": shot.get("visualDescription", ""),
                        "characterRefs": [item["id"] for item in character_inputs],
                    },
                )
                response.raise_for_status()
                body = response.json()
                task_id = self._task_id(body)
                result = await self._poll(client, task_id)
                output = result.get("output")
                if not isinstance(output, dict):
                    raise RuntimeError("PROVIDER_RESPONSE_INVALID")
                source_url = output.get("url")
                if not isinstance(source_url, str) or not source_url:
                    raise RuntimeError("PROVIDER_RESPONSE_INVALID")
                duration_ms = int(output.get("durationMs", float(shot["durationSec"]) * 1000))
                return {
                    "id": f"visual-{shot['id']}-{task_id}",
                    "shotId": shot["id"],
                    "type": "dynamic-video",
                    "mediaType": "video",
                    "durationMs": duration_ms,
                    "provider": "real",
                    "modelVersion": self._model,
                    "requestReference": task_id,
                    "sourceUrl": source_url,
                    "fallback": False,
                    "characterRefs": [item["id"] for item in character_inputs],
                }
        except RuntimeError as error:
            if str(error) in {"PROVIDER_TIMEOUT", "PROVIDER_GENERATION_FAILED"}:
                raise
            if self._fallback is None:
                raise
            return {**self._fallback, "provider": "fallback", "fallback": True}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            if self._fallback is None:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error
            return {**self._fallback, "provider": "fallback", "fallback": True}

    async def _poll(self, client: httpx.AsyncClient, task_id: str) -> dict[str, object]:
        for attempt in range(self._max_poll_attempts):
            response = await client.get(f"/tasks/{task_id}")
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            status = body.get("status")
            if status in {"succeeded", "completed"}:
                return body
            if status in {"failed", "cancelled"}:
                raise RuntimeError("PROVIDER_GENERATION_FAILED")
            if attempt + 1 < self._max_poll_attempts:
                await asyncio.sleep(self._poll_interval)
        raise RuntimeError("PROVIDER_TIMEOUT")

    @staticmethod
    def _task_id(body: object) -> str:
        if not isinstance(body, dict) or not isinstance(body.get("taskId"), str):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return str(body["taskId"])
