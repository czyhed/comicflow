from __future__ import annotations

import httpx

from comicflow.domain.models import JsonObject


class ModerationHttpProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "moderation-v1",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport

    async def moderate(self, text: str) -> JsonObject:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    "/moderation",
                    json={"model": self._model, "input": text},
                )
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException:
            return self._review("PROVIDER_TIMEOUT")
        except httpx.HTTPError as error:
            raise RuntimeError("PROVIDER_HTTP_ERROR") from error
        except (ValueError, TypeError) as error:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

        if not isinstance(body, dict) or body.get("result") not in {"approve", "block", "review"}:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        result = str(body["result"])
        return {
            "status": {"approve": "approved", "block": "blocked", "review": "review"}[result],
            "provider": "real",
            "modelVersion": self._model,
            **({"reasonCode": "UNSAFE_CONTENT"} if result == "block" else {}),
        }

    def _review(self, reason_code: str) -> JsonObject:
        return {
            "status": "review",
            "provider": "real",
            "modelVersion": self._model,
            "reasonCode": reason_code,
        }
