from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import os
import time
from typing import Any
from urllib.parse import quote

import httpx

from comicflow.domain.models import JsonObject
from comicflow.providers.h3_inputs import image_data
from comicflow.providers.image_checkpoints import (
    Checkpoint,
    ImageResponseError,
    ImageTaskError,
    report,
)

_ASYNC_SUBMIT = "/services/aigc/text2image/image-synthesis"
_V2_MODELS = {
    'wan2.2-t2i-flash', 'wan2.2-t2i-plus', 'wanx2.1-t2i-turbo',
    'wanx2.1-t2i-plus', 'wanx2.0-t2i-turbo',
}
_logger = logging.getLogger(__name__)


def resolve_image_protocol(model: str, protocol: str = 'auto') -> str:
    known = 'wan26-image' if model == 'wan2.6-image' else 'wan-v2' if model in _V2_MODELS else None
    if protocol not in {'auto', 'wan-v2', 'wan26-image'}:
        raise RuntimeError('PROVIDER_CONFIG_INVALID')
    if known and protocol not in {'auto', known}:
        raise RuntimeError('IMAGE_MODEL_UNSUPPORTED')
    if protocol == 'auto':
        if not known and model.startswith(('wan', 'qwen-image')):
            raise RuntimeError('IMAGE_MODEL_UNSUPPORTED')
        # Preserve existing deployments using aliases for the original V2 adapter.
        return known or 'wan-v2'
    return protocol


def _failure_code(body: object, status: int = 0) -> str:
    code = str(body.get('code', '')) if isinstance(body, dict) else ''
    if code in {'AllocationQuota.FreeTierOnly', 'QuotaExhausted', 'InsufficientBalance'}:
        return 'IMAGE_QUOTA_EXHAUSTED'
    if code in {'DataInspectionFailed', 'InputDataInspectionFailed', 'OutputDataInspectionFailed'}:
        return 'IMAGE_CONTENT_REJECTED'
    if status in {401, 403} or code in {'InvalidApiKey', 'AccessDenied'}:
        return 'PROVIDER_AUTH_FAILED'
    if status == 429 or code.startswith('Throttling'):
        return 'IMAGE_RATE_LIMITED'
    if status in {400, 404, 422} or code.startswith(('InvalidParameter', 'InvalidModel')):
        return 'IMAGE_REQUEST_INVALID'
    return 'PROVIDER_HTTP_ERROR' if status else 'PROVIDER_GENERATION_FAILED'


def _response_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as error:
        if response.is_error:
            raise ImageResponseError(
                _failure_code({}, response.status_code), response.status_code, {},
            ) from error
        raise RuntimeError('PROVIDER_RESPONSE_INVALID') from error
    if response.is_error:
        failure = _failure_code(body, response.status_code)
        _logger.warning('Image provider rejected request: status=%s error=%s',
                        response.status_code, failure)
        raise ImageResponseError(failure, response.status_code, body)
    if not isinstance(body, dict):
        raise RuntimeError('PROVIDER_RESPONSE_INVALID')
    if body.get('code'):
        raise ImageResponseError(_failure_code(body), response.status_code, body)
    return body


class BailianImageProvider:
    """Real Bailian (DashScope) wanx text-to-image via the async task API.

    Submits a 9:16 keyframe prompt per shot, polls ``/tasks/{id}`` until the image
    is ready, downloads the result and (with an asset store) persists it, returning
    the same metadata shape other visual providers use.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        model: str = "wanx2.1-t2i-plus",
        size: str = "720*1280",
        image_protocol: str = 'auto',
        submit_path: str = '',
        query_path: str = '',
        timeout_seconds: float = 180.0,
        poll_interval_seconds: float = 4.0,
        transport: httpx.AsyncBaseTransport | None = None,
        asset_store: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("BAILIAN_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._size = size
        self._image_protocol = image_protocol
        self._submit_path = submit_path
        self._query_path = query_path or '/tasks/{task_id}'
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._transport = transport
        self._asset_store = asset_store

    @property
    def supports_image_edit(self) -> bool:
        return resolve_image_protocol(self._model, self._image_protocol) == 'wan26-image'

    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject], *,
        checkpoint: Checkpoint | None = None, resume: JsonObject | None = None,
    ) -> JsonObject:
        protocol = resolve_image_protocol(self._model, self._image_protocol)
        prompt = _build_prompt(shot, character_inputs)
        parameters: JsonObject = {'size': self._size, 'n': 1}
        inputs: JsonObject = {'prompt': prompt}
        default_path = _ASYNC_SUBMIT
        task_id = (resume or {}).get('taskId')
        source_image = None if task_id else await self._source_image(shot)
        if source_image is not None:
            if protocol != 'wan26-image':
                raise RuntimeError('IMAGE_EDIT_UNSUPPORTED')
            inputs = {
                'messages': [{
                    'role': 'user',
                    'content': [{'text': prompt}, {'image': source_image}],
                }]
            }
            parameters.update({
                'enable_interleave': False,
                'prompt_extend': True,
                'watermark': False,
            })
            default_path = '/services/aigc/image-generation/generation'
        elif protocol == 'wan26-image':
            inputs = {'messages': [{'role': 'user', 'content': [{'text': prompt}]}]}
            parameters.update({'enable_interleave': True, 'max_images': 1})
            default_path = '/services/aigc/image-generation/generation'
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-Async": "enable",
        }
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            payload = {
                "model": self._model,
                "input": inputs,
                "parameters": parameters,
            }
            if not task_id:
                await report(checkpoint, 'submitting')
                try:
                    response = await client.post(self._submit_path or default_path, json=payload)
                    body = _response_body(response)
                except httpx.TimeoutException as error:
                    raise RuntimeError("PROVIDER_TIMEOUT") from error
                except httpx.HTTPError as error:
                    raise RuntimeError("PROVIDER_HTTP_ERROR") from error
                except (ValueError, TypeError) as error:
                    raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error

                output = body.get('output')
                task_id = output.get('task_id') if isinstance(output, dict) else None
                if not isinstance(task_id, str) or not task_id:
                    raise RuntimeError("PROVIDER_RESPONSE_INVALID")

                await report(checkpoint, 'polling', {'taskId': task_id})

            url = await self._poll(client, task_id, protocol)

        # Result URLs belong to asset hosts, not to the authenticated API origin.
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
        ) as download_client:
            try:
                image = await download_client.get(url)
                image.raise_for_status()
            except httpx.TimeoutException as error:
                raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPError as error:
                raise RuntimeError("IMAGE_DOWNLOAD_FAILED") from error

        import io

        from PIL import Image

        try:
            with Image.open(io.BytesIO(image.content)) as opened:
                opened.load()
                width, height = opened.size
                output = io.BytesIO()
                opened.convert('RGB').save(output, format='PNG')
                image_bytes = output.getvalue()
        except (OSError, ValueError) as error:
            raise RuntimeError('REFERENCE_IMAGE_INVALID') from error
        shot_id = str(shot.get("id", ""))
        asset: JsonObject = {
            "id": f"visual-{shot_id}-{task_id[:8]}",
            "shotId": shot_id,
            "type": "keyframe",
            "mediaType": "image",
            "width": int(width),
            "height": int(height),
            "durationMs": round(float(shot.get("durationSec") or 4.0) * 1000),
            "provider": "wanx",
            "modelVersion": self._model,
            "requestReference": task_id,
            "sourceUrl": url,
            "characterRefs": [str(item.get("id", "")) for item in character_inputs],
        }
        if self._asset_store is not None and image.content:
            object_key = f"visuals/{shot_id}/{os.urandom(4).hex()}.png"
            await self._asset_store.put_bytes(
                object_key=object_key,
                content=image_bytes,
                content_type="image/png",
            )
            asset["objectKey"] = object_key
            asset["sizeBytes"] = len(image_bytes)
        return asset

    async def _source_image(self, shot: JsonObject) -> str | None:
        """Read an approved image locally before sending it to image editing."""
        key = shot.get('sourceImageObjectKey')
        if key:
            if self._asset_store is None or not callable(
                getattr(self._asset_store, 'get_bytes', None)
            ):
                raise RuntimeError('IMAGE_EDIT_SOURCE_UNREADABLE')
            try:
                content = await self._asset_store.get_bytes(str(key), 10 * 1024 * 1024)
                return image_data(content)
            except RuntimeError:
                raise
            except Exception as error:
                raise RuntimeError('IMAGE_EDIT_SOURCE_UNREADABLE') from error

        value = shot.get('sourceImageUrl')
        if not isinstance(value, str) or not value:
            return None
        if value.startswith('data:'):
            try:
                header, encoded = value.split(',', 1)
                if header not in {
                    'data:image/png;base64',
                    'data:image/jpeg;base64',
                    'data:image/webp;base64',
                }:
                    raise ValueError('unsupported image type')
                return image_data(base64.b64decode(encoded, validate=True))
            except (ValueError, binascii.Error) as error:
                raise RuntimeError('IMAGE_EDIT_SOURCE_INVALID') from error
        if value.startswith(('http://', 'https://')):
            return value
        raise RuntimeError('IMAGE_EDIT_SOURCE_INVALID')

    async def _poll(self, client: httpx.AsyncClient, task_id: str, protocol: str) -> str:
        deadline = time.monotonic() + self._timeout
        while time.monotonic() < deadline:
            try:
                response = await client.get(
                    self._query_path.replace('{task_id}', quote(task_id, safe=''))
                )
                body = _response_body(response)
                output = body.get('output')
                if not isinstance(output, dict):
                    raise RuntimeError('PROVIDER_RESPONSE_INVALID')
            except httpx.TimeoutException as error:
                raise RuntimeError("PROVIDER_TIMEOUT") from error
            except httpx.HTTPError as error:
                raise RuntimeError("PROVIDER_HTTP_ERROR") from error
            status = str(output.get("task_status", ""))
            if status == "SUCCEEDED":
                if protocol == 'wan26-image':
                    choices = output.get('choices')
                    if isinstance(choices, list):
                        for choice in choices:
                            message = choice.get('message') if isinstance(choice, dict) else None
                            content = message.get('content') if isinstance(message, dict) else None
                            if not isinstance(content, list):
                                continue
                            for item in content:
                                url = item.get('image') if isinstance(item, dict) else None
                                if isinstance(url, str) and url.startswith(('https://', 'http://')):
                                    return url
                    raise RuntimeError('PROVIDER_RESPONSE_INVALID')
                results = output.get("results") or []
                if results and isinstance(results[0], dict):
                    url = results[0].get("url")
                    if isinstance(url, str) and url:
                        return url
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            if status in {"FAILED", "CANCELED"}:
                raise ImageTaskError(_failure_code(output))
            await asyncio.sleep(self._poll_interval)
        raise RuntimeError("PROVIDER_TIMEOUT")


def _build_prompt(shot: JsonObject, character_inputs: list[JsonObject]) -> str:
    if shot.get('imagePurpose') in {'character-reference-board', 'character-reference-text-board'}:
        return str(shot['visualDescription'])
    if shot.get('imagePurpose') in {
        'character-reference', 'character-reference-view', 'scene-background'
    }:
        # The declared style comes from the caller's prompt. Hard-coding 漫画风格
        # here used to contradict a photorealistic request and win, so every
        # reference image came out as 2D anime while the videos stayed realistic.
        return str(shot['visualDescription']) + ' 竖版9:16，勿加文字和水印。'
    parts: list[str] = []
    scene = str(shot.get("sceneId", ""))
    title = str(shot.get("title", "") or f"镜头 {shot.get('order', '')}")
    parts.append(f"竖屏电影感关键帧，镜头：{title}")
    if scene:
        parts.append(f"场景{scene}")
    action = str(shot.get("action", "")).strip()
    emotion = str(shot.get("emotion", "")).strip()
    description = str(shot.get("visualDescription", "")).strip()
    if description:
        parts.append(f"画面：{description}")
    if action or emotion:
        parts.append(f"动作：{action}；情绪：{emotion}".strip("；"))
    for item in character_inputs:
        name = str(item.get("name", "")).strip()
        appearance = str(item.get("appearance", "")).strip()
        clothing = str(item.get("clothing", "")).strip()
        if name:
            parts.append(f"角色{name}：{appearance} {clothing}".strip())
    # The project style (apply_video_style puts it in visualStyle) decides the medium.
    # A fixed "真实摄影质感" here pulled 2D / ink-wash projects towards photorealism.
    style = str(shot.get("visualStyle", "")).strip()
    parts.append(f"画面风格：{style}" if style else "画面风格与上述描述一致")
    parts.append("电影感光影，细节丰富，竖版 9:16 构图，人物居画面主体，勿加文字水印。")
    return "，".join(parts)
