"""OpenAI-compatible image generation provider (sync Chat Completions format)."""

import base64
import re
from typing import Any

import httpx

from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore
from comicflow.providers.image_checkpoints import Checkpoint, report


class OpenAIImageProvider:
    """Image provider for OpenAI-compatible APIs using Chat Completions format.

    Supports synchronous image generation where the model returns Base64-encoded
    images embedded in Markdown format: ![image](data:image/png;base64,...)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 180,
        asset_store: AssetStore | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._asset_store = asset_store
        self._transport = transport

    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject], *,
        checkpoint: Checkpoint | None = None, resume: JsonObject | None = None,
    ) -> JsonObject:
        """Generate a single image asset for the given shot specification."""
        if shot.get('sourceImageUrl') or shot.get('sourceImageObjectKey'):
            raise RuntimeError('IMAGE_EDIT_UNSUPPORTED')
        prompt = self._build_prompt(shot, character_inputs)

        if not prompt:
            raise RuntimeError("IMAGE_PROMPT_REQUIRED")

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            try:
                # Build request payload with optional quality/style parameters
                payload: dict[str, Any] = {
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                }

                # Add optional parameters for models that support them (DALL-E 3, gpt-image-*)
                # These improve quality for character reference images
                purpose = shot.get("imagePurpose", "character-reference")
                if purpose == "character-reference":
                    # Request highest quality and vivid style for character references
                    payload["quality"] = "hd"
                    payload["style"] = "vivid"

                await report(checkpoint, 'submitting')
                response = await client.post(
                    "/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
            except httpx.TimeoutException as error:
                raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPStatusError as error:
                raise RuntimeError(
                    self._map_http_error(error.response.status_code, error.response)
                ) from error
            except httpx.HTTPError as error:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error
            except (ValueError, KeyError) as error:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

        # Parse response
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

        # Extract Base64 image from Markdown format
        match = re.search(
            r"data:image/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=]+)",
            str(content),
        )
        if not match:
            raise RuntimeError("IMAGE_RESPONSE_INVALID")

        image_format = match.group(1)
        if image_format == "jpg":
            image_format = "jpeg"

        try:
            image_data = base64.b64decode(match.group(2), validate=True)
        except Exception as error:
            raise RuntimeError("IMAGE_DECODE_FAILED") from error

        if len(image_data) < 50:
            raise RuntimeError("IMAGE_TOO_SMALL")

        # Store to asset store
        asset: JsonObject = {
            "id": f"img-{shot['id']}",
            "shotId": shot.get("id"),
            "type": "reference-image",
            "mediaType": "image",
            "provider": "openai-image",
            "modelVersion": self._model,
            "bytes": len(image_data),
            "fallback": False,
        }

        if self._asset_store is not None:
            purpose = shot.get("imagePurpose", "character-reference")
            object_key = f"{purpose}/{shot['id']}.{image_format}"
            await self._asset_store.put_bytes(
                object_key=object_key,
                content=image_data,
                content_type=f"image/{image_format}",
            )
            asset["objectKey"] = object_key
            if hasattr(self._asset_store, "presigned_get_url"):
                asset["url"] = await self._asset_store.presigned_get_url(object_key)
        else:
            asset["dataUri"] = f"data:image/{image_format};base64,{match.group(2)}"

        return asset

    def _build_prompt(self, shot: JsonObject, character_inputs: list[JsonObject]) -> str:
        """Build the text prompt from shot and character specifications."""
        parts: list[str] = []

        # Primary description
        if shot.get("visualDescription"):
            parts.append(str(shot["visualDescription"]).strip())

        # Character details
        for char in character_inputs:
            char_parts = []
            if char.get("name"):
                char_parts.append(f"角色：{char['name']}")
            if char.get("appearance"):
                char_parts.append(f"外观：{char['appearance']}")
            if char.get("clothing"):
                char_parts.append(f"服装：{char['clothing']}")
            if char_parts:
                parts.append("。".join(char_parts))

        # The caller has already compiled the selected visual Skill into
        # visualDescription. Do not append a provider-specific art style here:
        # the old hard-coded 漫画风格 overrode approved character and scene styles.
        purpose = shot.get("imagePurpose", "character-reference")
        if purpose == "character-reference":
            parts.append(
                "全身正面角色参考图，单一人物，纯净背景，面部和服装细节清晰。"
                "材质、线条、笔触和光影遵循已给定画风，保持人物身份与服装配色。"
            )
        elif purpose == "scene-background":
            parts.append("无人物的场景背景参考图，广角全景，环境细节清晰")
        else:
            parts.append("高质量，主体清晰，细节完整")

        return "。".join(parts)

    def _map_http_error(self, status: int, response: Any) -> str:
        """Map HTTP status codes to domain error codes."""
        if status in {401, 403}:
            return "PROVIDER_AUTH_FAILED"
        if status == 429:
            return "IMAGE_RATE_LIMITED"
        if status in {400, 422}:
            return "IMAGE_REQUEST_INVALID"
        if status >= 500:
            return "PROVIDER_SERVER_ERROR"
        return "PROVIDER_HTTP_ERROR"
