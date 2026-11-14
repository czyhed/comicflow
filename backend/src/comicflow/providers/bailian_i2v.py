"""DashScope Wan video synthesis behind the production visual capability."""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import ipaddress
import logging
import re
import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from PIL import Image

from comicflow.domain.models import JsonObject
from comicflow.providers.video_checkpoints import Checkpoint, VideoStageError, report

_logger = logging.getLogger(__name__)


def _failure_code(body: object, status: int = 0) -> str:
    code = str(body.get('code', '')) if isinstance(body, dict) else ''
    if code in {'AllocationQuota.FreeTierOnly', 'QuotaExhausted', 'InsufficientBalance'}:
        return 'VIDEO_QUOTA_EXHAUSTED'
    if code in {'DataInspectionFailed', 'InputDataInspectionFailed', 'OutputDataInspectionFailed'}:
        return 'VIDEO_CONTENT_REJECTED'
    if status in {401, 403} or code in {'InvalidApiKey', 'AccessDenied'}:
        return 'PROVIDER_AUTH_FAILED'
    if status == 429 or code.startswith('Throttling'):
        return 'VIDEO_RATE_LIMITED'
    if status in {400, 404, 422} or code.startswith(('InvalidParameter', 'InvalidModel')):
        return 'VIDEO_REQUEST_INVALID'
    return 'PROVIDER_HTTP_ERROR' if status else 'PROVIDER_GENERATION_FAILED'


def _log_failure(body: object, status: int = 0) -> None:
    details = body if isinstance(body, dict) else {}
    safe = {}
    for field in ('code', 'request_id'):
        value = str(details.get(field, ''))
        safe[field] = value if re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value) else 'unavailable'
    _logger.warning('Video provider failure: status=%s code=%s request_id=%s',
                    status, safe['code'], safe['request_id'])


def _image_data(content: bytes) -> str:
    if not content or len(content) > 10 * 1024 * 1024:
        raise RuntimeError('REFERENCE_IMAGE_INVALID')
    try:
        with Image.open(io.BytesIO(content)) as img:
            if img.format not in {'PNG', 'JPEG', 'WEBP', 'BMP'} or not all(
                240 <= side <= 8000 for side in img.size
            ):
                raise RuntimeError('REFERENCE_IMAGE_INVALID')
            img.load()
            buffer = io.BytesIO()
            img.convert('RGB').save(buffer, format='PNG')
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise RuntimeError('REFERENCE_IMAGE_INVALID') from error
    encoded_image = buffer.getvalue()
    if len(encoded_image) > 10 * 1024 * 1024:
        raise RuntimeError('REFERENCE_IMAGE_INVALID')
    return 'data:image/png;base64,' + base64.b64encode(encoded_image).decode('ascii')


def _local_url(url: str) -> bool:
    hostname = urlparse(url).hostname or ''
    if hostname == 'localhost' or hostname.endswith(('.localhost', '.local')):
        return True
    try:
        return not ipaddress.ip_address(hostname).is_global
    except ValueError:
        return '.' not in hostname


class BailianImageToVideoProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        model: str = "wan2.2-i2v-flash",
        resolution: str = "480P",
        generation_type: str = "i2v",
        submit_path: str = '',
        query_path: str = '',
        timeout_seconds: float = 600,
        poll_interval_seconds: float = 5,
        transport: httpx.AsyncBaseTransport | None = None,
        asset_store: Any | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("PROVIDER_NOT_CONFIGURED")
        self._api_key, self._base_url, self._model = api_key, base_url.rstrip("/"), model
        self._resolution, self.generation_type = resolution, generation_type
        self._submit_path = submit_path or '/services/aigc/video-generation/video-synthesis'
        self._query_path = query_path or '/tasks/{task_id}'
        self._timeout, self._poll_interval = timeout_seconds, poll_interval_seconds
        self._transport, self._asset_store = transport, asset_store

    def _request(self, shot: JsonObject, characters: list[JsonObject]) -> JsonObject:
        mode = shot.get("generationMode", "t2va")
        if (mode not in {"t2va", "i2va"}
                or shot.get("lastFrameUrl") or shot.get("referenceImages")):
            raise RuntimeError("VIDEO_MODE_UNSUPPORTED")
        duration = shot.get("durationSec", 5)
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise RuntimeError("VIDEO_DURATION_INVALID")
        allowed = (
            {5}
            if self._model
            in {
                "wan2.2-i2v-flash",
                "wan2.2-i2v-plus",
                "wanx2.1-i2v-plus",
                "wan2.2-t2v-plus",
                "wanx2.1-t2v-plus",
            }
            else {3, 4, 5}
            if self._model in {"wanx2.1-i2v-turbo", "wanx2.1-t2v-turbo"}
            else None
        )
        if (
            duration != int(duration)
            or not 1 <= duration <= 15
            or (allowed is not None and duration not in allowed)
        ):
            raise RuntimeError("VIDEO_DURATION_INVALID")
        if self._resolution not in {"480P", "720P", "1080P"}:
            raise RuntimeError("VIDEO_RESOLUTION_INVALID")
        if self._model.startswith(("wan2.6", "wan2.7")) and (
            duration < 2 or self._resolution == "480P"
        ):
            raise RuntimeError("VIDEO_RESOLUTION_INVALID")
        limited = {
            "wan2.2-i2v-plus": {"480P", "1080P"},
            "wanx2.1-i2v-turbo": {"480P", "720P"},
            "wanx2.1-i2v-plus": {"720P"},
        }
        if self._model in limited and self._resolution not in limited[self._model]:
            raise RuntimeError("VIDEO_RESOLUTION_INVALID")
        first = shot.get("firstFrameUrl")
        if self.generation_type == "i2v" and not first:
            raise RuntimeError("VIDEO_FIRST_FRAME_REQUIRED")
        if self.generation_type == "t2v" and (first or mode == "i2va"):
            raise RuntimeError("VIDEO_MODE_UNSUPPORTED")
        if first:
            if str(first).startswith('data:'):
                try:
                    header, data = str(first).split(',', 1)
                    if header not in {
                        'data:image/png;base64', 'data:image/jpeg;base64',
                        'data:image/webp;base64', 'data:image/bmp;base64',
                    } or len(data) > 14 * 1024 * 1024:
                        raise ValueError('invalid image data')
                    _image_data(base64.b64decode(data, validate=True))
                except (ValueError, binascii.Error) as error:
                    raise RuntimeError('REFERENCE_IMAGE_INVALID') from error
            parsed = None if str(first).startswith("data:image/") else urlparse(str(first))
            if parsed is not None and (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path.lower().endswith((".mp4", ".mov", ".webm"))
            ):
                raise RuntimeError("REFERENCE_IMAGE_INVALID")
        parts = [
            str(shot.get(k) or "").strip()
            for k in ("visualDescription", "action", "cameraMovement", "visualStyle")
        ]
        dialogue = str(shot.get("dialogue") or "").strip()
        if dialogue:
            parts.append(f"对白：{dialogue}")
        parts += [
            f"{c.get('name', '')}：{c.get('appearance', '')}；{c.get('clothing', '')}"
            for c in characters
        ]
        prompt = "。".join(part for part in parts if part)
        if not prompt:
            raise RuntimeError("VIDEO_PROMPT_REQUIRED")

        # 添加质量约束，减少 AI 味
        quality_constraints = [
            "真实自然的运动节奏",
            "避免过度平滑或机械化的动作",
            "保持画面细节和纹理的真实感",
            "自然的光影变化"
        ]
        prompt = prompt + "。" + "，".join(quality_constraints)

        limit = 1500 if self._model.startswith(("wan2.5", "wan2.6", "wan2.7")) else 800
        if len(prompt) > limit:
            raise RuntimeError("VIDEO_PROMPT_TOO_LONG")
        inputs: JsonObject = {"prompt": prompt}
        if first:
            if self._model.startswith('wan2.7') and self.generation_type == 'i2v':
                inputs['media'] = [{'type': 'first_frame', 'url': first}]
            else:
                inputs["img_url"] = first

        parameters: JsonObject = {
            "duration": int(duration),
            "resolution": self._resolution,
            "prompt_extend": False,
        }
        if self.generation_type == "t2v":
            if self._model.startswith("wan2.7"):
                parameters["ratio"] = "9:16"
            else:
                parameters.pop("resolution")
                parameters["size"] = {"480P": "480*832", "720P": "720*1280", "1080P": "1080*1920"}[
                    self._resolution
                ]
        return {"model": self._model, "input": inputs, "parameters": parameters}

    def prepare_preview(self, shot: JsonObject, characters: list[JsonObject]) -> JsonObject:
        request = self._request(shot, characters)
        return {'model': request['model'], 'adapter': 'bailian-video',
                'parameters': request['parameters'], 'mode': self.generation_type,
                'images': [{'url': shot['firstFrameUrl'], 'role': 'first_frame',
                            'label': '首帧'}] if shot.get('firstFrameUrl') else [],
                'prompt': {'kind': 'submission', 'text': request['input']['prompt'],
                           'platformOptimization': False},
                'calls': {'text': 0, 'video': 1}}

    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject], *,
        checkpoint: Checkpoint | None = None, resume: JsonObject | None = None,
    ) -> JsonObject:
        resume = resume or {}
        task_id = resume.get('taskId')
        stage = 'video_poll' if task_id else 'video_submit'
        payload: JsonObject = resume.get('compiled') or {}
        if not task_id:
            await report(checkpoint, 'preparing')
            request_shot = dict(shot)

            # 处理首帧图片
            object_key = request_shot.get("firstFrameObjectKey")
            if (object_key and self._asset_store is not None
                    and hasattr(self._asset_store, "get_bytes")):
                try:
                    content = await self._asset_store.get_bytes(str(object_key), 10 * 1024 * 1024)
                except Exception as error:
                    raise RuntimeError("VIDEO_FIRST_FRAME_UNREADABLE") from error
                request_shot["firstFrameUrl"] = _image_data(content)
            elif request_shot.get("firstFrameUrl"):
                first = str(request_shot['firstFrameUrl'])
                if not first.startswith('data:') and _local_url(first):
                    raise RuntimeError("VIDEO_FIRST_FRAME_UNREACHABLE")

            payload = self._request(request_shot, character_inputs)
            await report(checkpoint, 'prepared', {'compiled': {
                'model': self._model, 'parameters': payload['parameters'],
                'input': {'prompt': payload['input']['prompt']},
            }})
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                headers={"Authorization": f"Bearer {self._api_key}", "X-DashScope-Async": "enable"},
            ) as client:
                if not task_id:
                    await report(checkpoint, 'submitting')
                    response = await client.post(
                        self._submit_path, json=payload
                    )
                    response.raise_for_status()
                    task_id = response.json()["output"]["task_id"]
                    if not isinstance(task_id, str) or not task_id:
                        raise RuntimeError("PROVIDER_RESPONSE_INVALID")
                    await report(checkpoint, 'polling', {'taskId': task_id})
                stage = 'video_poll'
                deadline = time.monotonic() + self._timeout
                while True:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("PROVIDER_TIMEOUT")
                    status = await client.get(
                        self._query_path.replace('{task_id}', quote(task_id, safe=''))
                    )
                    status.raise_for_status()
                    output = status.json()["output"]
                    if output.get("task_status") == "SUCCEEDED":
                        video_url = output["video_url"]
                        break
                    if output.get("task_status") in {"FAILED", "CANCELED", "UNKNOWN"}:
                        _log_failure({**output, 'request_id': status.json().get('request_id', '')})
                        raise VideoStageError(_failure_code(output), stage, terminal=True)
                    await asyncio.sleep(self._poll_interval)
            stage = 'video_result'
            await report(checkpoint, 'downloading')
            parsed = urlparse(video_url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, follow_redirects=True
            ) as download:
                video = await download.get(video_url)
                video.raise_for_status()
                if not video.content:
                    raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        except httpx.TimeoutException as error:
            raise VideoStageError("PROVIDER_TIMEOUT", stage) from error
        except httpx.HTTPStatusError as error:
            try:
                failure_body = error.response.json()
            except ValueError:
                failure_body = {}
            _log_failure(failure_body, error.response.status_code)
            code = _failure_code(failure_body, error.response.status_code)
            raise VideoStageError(code, stage, status=error.response.status_code) from error
        except httpx.HTTPError as error:
            raise RuntimeError("PROVIDER_HTTP_ERROR") from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID") from error
        asset: JsonObject = {
            "id": f"visual-{shot['id']}-{task_id}",
            "shotId": shot["id"],
            "type": "dynamic-video",
            "mediaType": "video",
            "provider": "bailian",
            "modelVersion": self._model,
            "requestReference": task_id,
            "sourceUrl": video_url,
            "bytes": len(video.content),
            "durationSec": payload["parameters"]["duration"],
            "resolution": self._resolution,
            "generationMode": self.generation_type,
            "prompt": payload["input"]["prompt"],
            "fallback": False,
        }
        if self._asset_store is not None:
            key = f"videos/{shot['id']}/{task_id}.mp4"
            await self._asset_store.put_bytes(key, video.content, "video/mp4")
            asset["objectKey"] = key
        return asset
