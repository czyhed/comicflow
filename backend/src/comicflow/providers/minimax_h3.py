"""MiniMax H3 video-generation adapter.

The provider keeps the vendor API behind the DynamicVisualProvider seam.  The
endpoint and model are configurable because the H3 deployment used by
Compshare may expose a compatible gateway rather than the public MiniMax host.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from typing import Any

import httpx

from comicflow.domain.models import JsonObject
from comicflow.providers.h3_context_ir import compile_chinese_intent
from comicflow.providers.h3_errors import (
    H3_MAX_PROMPT_CHARACTERS,
    H3BusinessError,
    H3PromptLengthError,
    H3RequestError,
    H3ResponseError,
    H3TaskError,
    ResponseStage,
)
from comicflow.providers.h3_inputs import prepare_images, text_metadata
from comicflow.providers.h3_skill import H3SkillPromptWriter, reference_plan
from comicflow.providers.video_checkpoints import Checkpoint, report

_logger = logging.getLogger(__name__)


def safe_status_token(value: object) -> str | None:
    """A bounded, ASCII-only view of an upstream status value, or None.

    The token is what a diagnostic needs; anything else in the field (a URL, a
    message, punctuation) is refused rather than logged.
    """
    if not isinstance(value, str):
        return None
    token = value.strip()[:32]
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', token):
        return None
    return token


class MinimaxH3Provider:
    """Submit, poll, download, and persist one H3 video generation."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://cp.compshare.cn",
        model: str = "MiniMax-H3",
        resolution: str = "768P",
        prompt_mode: str = "local-skill",
        submit_path: str = "/minimax/v2/video_generation",
        query_path: str = "/minimax/v2/query/video_generation/{task_id}",
        timeout_seconds: float = 600.0,
        poll_interval_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        asset_store: Any | None = None,
        prompt_writer: H3SkillPromptWriter | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY_REQUIRED")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        if prompt_mode not in {'local-skill', 'context-ir'}:
            raise RuntimeError('PROVIDER_CONFIG_INVALID')
        self._prompt_mode = prompt_mode
        self._resolution = str(resolution or "768P").strip().upper()
        allowed_resolutions = {
            "MiniMax-H3": {"768P", "1080P", "2K"},
            "MiniMax-H3-Max": {"480P", "768P"},
        }.get(model, {"480P", "768P", "2K"})
        if self._resolution not in allowed_resolutions:
            raise RuntimeError("MINIMAX_RESOLUTION_INVALID")
        self._submit_path = submit_path
        self._query_path = query_path
        self._timeout = timeout_seconds
        self._poll_interval = max(0.0, poll_interval_seconds)
        self._transport = transport
        self._asset_store = asset_store
        self._prompt_writer = prompt_writer

    def set_prompt_writer(self, writer: H3SkillPromptWriter | None) -> None:
        self._prompt_writer = writer

    @property
    def prompt_description(self) -> str:
        return (
            '中文 + 优云 Context-IR（不调用本地文本扩写）'
            if self._prompt_mode == 'context-ir' else 'text + h3-prompt-writing'
        )

    def prepare_preview(self, shot: JsonObject, characters: list[JsonObject]) -> JsonObject:
        """Describe the actual request contract; never execute text or video models."""
        plan = reference_plan(shot, characters)
        if self._prompt_mode == 'context-ir':
            compiled = compile_chinese_intent(shot, characters)
            prompt = {'kind': 'submission', 'text': compiled['prompt'],
                      'rules': compiled['execution'], 'platformOptimization': True}
        else:
            if self._prompt_writer is None:
                raise RuntimeError('H3_PROMPT_WRITER_REQUIRED')
            prepared = self._prompt_writer.prepare_input(shot, characters)
            prompt = {'kind': 'expansion-input', 'text': prepared['user'],
                      'system': prepared['system'], 'platformOptimization': False,
                      'rules': {'skill': 'h3-prompt-writing', 'files': prepared['files'],
                                'sha256': prepared['sha256']}}
        # Reuse the request builder, including resolution precedence and ratio defaults.
        request = self._build_request({**shot, 'h3Prompt': prompt['text']}, characters)
        return {'model': request['model'], 'adapter': 'minimax-h3',
                'parameters': {key: request[key] for key in ('resolution', 'duration', 'ratio')},
                'mode': plan['mode'], 'images': plan['images'], 'prompt': prompt,
                'calls': {'text': int(self._prompt_mode == 'local-skill'), 'video': 1}}

    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject], *,
        checkpoint: Checkpoint | None = None, resume: JsonObject | None = None,
    ) -> JsonObject:
        resume = resume or {}
        task_id: str | None = resume.get('taskId')
        compiled = resume.get('compiled')
        request: JsonObject = {}
        if not task_id:
            if self._prompt_mode == 'local-skill' and self._prompt_writer is None:
                raise RuntimeError('H3_PROMPT_WRITER_REQUIRED')
            await report(checkpoint, 'preparing')
            reference_plan(shot, character_inputs)
            shot, character_inputs = await prepare_images(shot, character_inputs, self._asset_store)
            if compiled is None:
                if self._prompt_mode == 'context-ir':
                    compiled = compile_chinese_intent(shot, character_inputs)
                else:
                    assert self._prompt_writer is not None
                    await report(checkpoint, 'expanding')
                    compiled = await self._prompt_writer.write(shot, character_inputs)
            if len(compiled['prompt']) > H3_MAX_PROMPT_CHARACTERS:
                raise H3PromptLengthError(
                    len(compiled['prompt']),
                    text_expansion_attempted=self._prompt_mode == 'local-skill'
                )
            request = self._build_request(
                {**shot, 'h3Prompt': compiled['prompt']}, character_inputs)
            await report(checkpoint, 'prepared', {'compiled': text_metadata(compiled)})
        if compiled is None:
            raise RuntimeError('PROVIDER_RESPONSE_INVALID')
        stage: ResponseStage = 'h3_poll' if task_id else 'h3_submit'
        headers = {"Authorization": f"Bearer {self._api_key}"}
        idempotency_key = shot.get('providerIdempotencyKey')
        if isinstance(idempotency_key, str) and re.fullmatch(
            r'[A-Za-z0-9._:-]{1,128}', idempotency_key
        ):
            # Changing the processing route must not retrieve the old English task.
            headers['Idempotency-Key'] = (
                'comicflow-' + hashlib.sha256(
                    (f"{idempotency_key}\0{self._prompt_mode}\0"
                     f"{compiled['execution']['compilerVersion']}").encode()
                ).hexdigest()[:40]
                if self._prompt_mode == 'context-ir' else idempotency_key
            )
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            try:
                if task_id is None:
                    await report(checkpoint, 'submitting')
                    response = await client.post(self._submit_path, json=request)
                    response.raise_for_status()
                    body = response.json()
                    if H3BusinessError.matches(body):
                        raise H3BusinessError(body, 'h3_submit')
                    task_id = self._task_id(body)
                    await report(checkpoint, 'polling', {'taskId': task_id})
                stage = 'h3_poll'
                result = await self._poll(client, task_id)
                stage = 'h3_result'
                await report(checkpoint, 'downloading')
                video_url = self._video_url(result)
                # The returned asset host must never receive the gateway API key.
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport, follow_redirects=True
                ) as download_client:
                    video = await download_client.get(video_url)
                    video.raise_for_status()
            except httpx.HTTPError as error:
                raise H3RequestError(error, stage, task_id) from error
            except H3ResponseError:
                # Already carries its own stage, reason and task id; re-wrapping
                # it would overwrite the reason and lose what we just learned.
                raise
            except (ValueError, TypeError, KeyError) as error:
                raise H3ResponseError(stage, task_id=task_id) from error
            except RuntimeError as error:
                if str(error) == 'PROVIDER_RESPONSE_INVALID':
                    raise H3ResponseError(stage, task_id=task_id) from error
                raise

        asset: JsonObject = {
            "id": f"visual-{shot['id']}-{task_id}",
            "shotId": shot["id"],
            "type": "dynamic-video",
            "mediaType": "video",
            "provider": "minimax",
            "modelVersion": self._model,
            "requestReference": task_id,
            "sourceUrl": video_url,
            "bytes": len(video.content),
            "durationSec": compiled['plan']['durationSec'],
            "generationMode": compiled['plan']['mode'],
            "h3PromptMode": self._prompt_mode,
            "promptExecution": compiled['execution'],
            "h3Prompt": compiled['prompt'],
            "referenceCharacterIds": [str(item["id"]) for item in character_inputs],
            "fallback": False,
        }
        if self._asset_store is not None and video.content:
            object_key = f"videos/{shot['id']}/{task_id}.mp4"
            await self._asset_store.put_bytes(
                object_key=object_key, content=video.content, content_type="video/mp4"
            )
            asset["objectKey"] = object_key
        return asset

    def _build_request(
        self, shot: JsonObject, character_inputs: list[JsonObject]
    ) -> JsonObject:
        plan = reference_plan(shot, character_inputs)
        if not shot.get('h3Prompt'):
            raise RuntimeError('H3_PROMPT_WRITER_REQUIRED')
        payload: JsonObject = {
            "model": self._model,
            "content": [{
                "type": "text",
                "text": shot['h3Prompt'],
            }],
            "duration": plan['durationSec'],
            # Resolution is a provider setting. A stale shot value cannot
            # override the low-cost 768P default selected by the user.
            "resolution": self._resolution,
            "ratio": str(shot.get("aspectRatio") or "9:16"),
        }
        if self._prompt_mode == 'context-ir':
            payload['use_context_ir'] = True
        for item in plan['images']:
            payload["content"].append({
                "type": "image_url", "image_url": {"url": item['url']}, "role": item['role']
            })
        return payload

    async def _poll(self, client: httpx.AsyncClient, task_id: str) -> JsonObject:
        deadline = time.monotonic() + self._timeout
        saw_unknown_status = False
        while time.monotonic() < deadline:
            try:
                response = await client.get(self._query_path.replace("{task_id}", task_id))
                response.raise_for_status()
                body = response.json()
                if H3BusinessError.matches(body):
                    raise H3BusinessError(body, 'h3_poll', task_id)
            except httpx.HTTPError as error:
                raise H3RequestError(error, 'h3_poll', task_id) from error
            if not isinstance(body, dict):
                raise H3ResponseError('h3_poll', task_id=task_id)
            raw_task = body.get("task")
            task: JsonObject = raw_task if isinstance(raw_task, dict) else body
            status = str(task.get("status") or task.get("task_status") or "").lower()
            if status in {"succeeded", "success", "completed"}:
                return task
            if status in {"failed", "failure", "cancelled", "canceled"}:
                raise H3TaskError(status, task_id)
            if status not in {
                'pending', 'queued', 'running', 'processing', 'submitted', 'moderating',
            }:
                # Failing here would throw away a task the user already paid for,
                # and the response is the only place that status can be observed.
                # Record the safe token and keep polling to the deadline instead.
                saw_unknown_status = True
                _logger.warning(
                    'H3 poll returned an unrecognised status: task_id=%s status=%s',
                    task_id, safe_status_token(task.get("status")) or 'unreportable',
                )
            await asyncio.sleep(self._poll_interval)
        if saw_unknown_status:
            raise H3ResponseError('h3_poll', 'unknown_status', task_id=task_id)
        raise H3ResponseError('h3_poll', 'timeout', task_id=task_id)

    @staticmethod
    def _task_id(body: object) -> str:
        if not isinstance(body, dict):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        task_id = body.get("task_id") or body.get("taskId")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        return task_id

    @staticmethod
    def _video_url(body: JsonObject) -> str:
        candidates = [body.get("video_url"), body.get("url")]
        content = body.get("content")
        if isinstance(content, dict):
            candidates.append(content.get("url"))
        output = body.get("output")
        if isinstance(output, dict):
            candidates.extend([output.get("video_url"), output.get("url")])
        for value in candidates:
            if isinstance(value, str) and value:
                return value
        raise RuntimeError("PROVIDER_RESPONSE_INVALID")

def minimax_config_from_env() -> dict[str, str]:
    """Return non-secret configuration for the probe script and runtime wiring."""
    _load_project_env()
    return {
        "api_key": os.getenv("MINIMAX_API_KEY", ""),
        "base_url": os.getenv("MINIMAX_BASE_URL", "https://cp.compshare.cn"),
        "model": os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-H3"),
        "resolution": os.getenv("MINIMAX_VIDEO_RESOLUTION", "768P"),
        "prompt_mode": os.getenv("MINIMAX_PROMPT_MODE", "local-skill"),
        "submit_path": os.getenv("MINIMAX_SUBMIT_PATH", "/minimax/v2/video_generation"),
        "query_path": os.getenv(
            "MINIMAX_QUERY_PATH", "/minimax/v2/query/video_generation/{task_id}"
        ),
    }


def _load_project_env() -> None:
    """Load the repository .env for standalone local scripts.

    Do not overwrite variables already supplied by the process environment.
    """
    from pathlib import Path

    for parent in Path.cwd(), *Path.cwd().parents:
        env_file = parent / ".env"
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name.startswith("MINIMAX_") and name not in os.environ:
                os.environ[name] = value
        return

