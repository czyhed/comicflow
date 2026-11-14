"""Xiangongyun MiniMax H3 multipart job adapter."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from comicflow.domain.models import JsonObject
from comicflow.providers.h3_context_ir import compile_chinese_intent
from comicflow.providers.h3_errors import (
    H3PromptLengthError,
    H3RequestError,
    H3ResponseError,
    H3TaskError,
    ResponseStage,
)
from comicflow.providers.h3_inputs import prepare_images, text_metadata
from comicflow.providers.h3_skill import reference_plan
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from comicflow.providers.video_checkpoints import Checkpoint, report

_SIZES = {
    '1.0P': (1344, 768), '0.9P': (1280, 704), '0.8P': (1216, 672),
    '0.7P': (1120, 640), '0.6P': (1024, 576), '0.5P': (960, 544),
    '0.4P': (832, 480),
}


class XiangongyunH3Provider(MinimaxH3Provider):
    """Keep the original H3 prompt and asset contract, changing only transport."""

    def __init__(self, *, base_url: str, resolution: str = '0.5P',
                 prompt_mode: str = 'context-ir',
                 inference_profile: str = 'turbo8_av_sol_gpu_te', **kwargs: Any) -> None:
        if resolution not in _SIZES or inference_profile not in {
            'turbo4_av_sol_gpu_te', 'turbo8_av_sol_gpu_te', 'quality_av_sol_gpu_te',
        }:
            raise RuntimeError('PROVIDER_CONFIG_INVALID')
        super().__init__(base_url=base_url, resolution='768P', prompt_mode=prompt_mode, **kwargs)
        self._resolution = resolution
        self._submit_path = '/api/v1/jobs'
        self._query_path = '/api/v1/jobs/{task_id}'
        self._inference_profile = inference_profile
        origin = urlsplit(self._base_url)
        if (origin.scheme not in {'http', 'https'} or not origin.hostname or origin.username
            or origin.path not in {'', '/'} or origin.query or origin.fragment):
            raise RuntimeError('PROVIDER_CONFIG_INVALID')

    @property
    def prompt_description(self) -> str:
        return ('中文 Context-IR 本地编译；仙宫云二次编译关闭'
                if self._prompt_mode == 'context-ir'
                else 'text + h3-prompt-writing；仙宫云二次编译关闭')

    @staticmethod
    def _execution(execution: JsonObject) -> JsonObject:
        return {**execution, 'useContextIr': False, 'compilePrompt': False,
                'adapter': 'xiangongyun-h3'}

    def prepare_preview(self, shot: JsonObject, characters: list[JsonObject]) -> JsonObject:
        preview = super().prepare_preview(shot, characters)
        ratio = str(shot.get('aspectRatio') or '9:16')
        width, height = self._dimensions(ratio)
        preview.update(adapter='xiangongyun-h3', model=self._model)
        preview['prompt']['platformOptimization'] = False
        preview['prompt']['rules'] = self._execution(preview['prompt']['rules'])
        if self._prompt_mode == 'context-ir':
            preview['prompt']['text'], manifest = self._wire_prompt(
                preview['prompt']['text'], reference_plan(shot, characters)
            )
            for index, item in enumerate(preview['images']):
                item['label'] = ('@' + manifest[index]['mention'] if manifest
                                 else '首帧图片' if item['role'] == 'first_frame' else '尾帧图片')
        preview['parameters'] = {
            'resolution': self._resolution, 'width': width, 'height': height,
            'duration': reference_plan(shot, characters)['durationSec'],
            'ratio': ratio, 'inferenceProfile': self._inference_profile,
            'compilePrompt': False,
        }
        return preview

    def _dimensions(self, ratio: str) -> tuple[int, int]:
        if ratio not in {'9:16', '16:9'}:
            raise RuntimeError('VIDEO_RATIO_UNSUPPORTED')
        width, height = _SIZES[self._resolution]
        return (height, width) if ratio == '9:16' else (width, height)

    @staticmethod
    def _image_bytes(url: object) -> bytes:
        if not isinstance(url, str) or not url.startswith('data:image/png;base64,'):
            raise RuntimeError('H3_REFERENCE_UNREADABLE')
        return base64.b64decode(url.partition(',')[2], validate=True)

    @staticmethod
    def _wire_prompt(prompt: str, plan: JsonObject) -> tuple[str, list[JsonObject]]:
        # Stable across preview/recovery, unlikely to collide with a persistent asset name.
        prefix = 'cf_' + hashlib.sha256(prompt.encode()).hexdigest()[:16]
        manifest: list[JsonObject] = []
        for index, item in enumerate(plan['images']):
            role = item['role']
            if role in {'first_frame', 'last_frame'}:
                prompt = prompt.replace(
                    item['label'], '首帧图片' if role == 'first_frame' else '尾帧图片'
                )
            else:
                name = f'{prefix}_{index + 1}'
                manifest.append({'mention': name, 'kind': 'image', 'index': len(manifest),
                                 'external_id': str(item.get('id') or name)[:128]})
                if item['label'] not in prompt:
                    raise RuntimeError('H3_REFERENCE_MODE_CONFLICT')
                prompt = prompt.replace(item['label'], '@' + name)
        if re.search(r'<Picture \d+>', prompt):
            raise RuntimeError('H3_REFERENCE_MODE_CONFLICT')
        if len(prompt) > 10000:
            error = H3PromptLengthError(len(prompt), text_expansion_attempted=False)
            error.detail['maxCharacters'] = 10000
            raise error
        return prompt, manifest

    def _submission(
        self, shot: JsonObject, compiled: JsonObject,
    ) -> tuple[dict[str, str], list[tuple[str, tuple[str, bytes, str]]]]:
        plan = compiled['plan']
        ratio = str(shot.get('aspectRatio') or '9:16')
        width, height = self._dimensions(ratio)
        prompt, manifest = self._wire_prompt(compiled['prompt'], plan)
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, item in enumerate(plan['images']):
            content = self._image_bytes(item['url'])
            role = item['role']
            if role in {'first_frame', 'last_frame'}:
                files.append((role, (f'{role}.png', content, 'image/png')))
            else:
                name = manifest[index]['mention']
                files.append(('reference_images', (f'{name}.png', content, 'image/png')))
        fields = {
            'task_mode': plan['mode'], 'prompt': prompt, 'aspect_ratio': ratio,
            'width': str(width), 'height': str(height),
            'duration': str(plan['durationSec']),
            'inference_profile': self._inference_profile, 'compile_prompt': 'false',
        }
        if manifest:
            fields['reference_manifest'] = json.dumps(manifest, ensure_ascii=False)
        return fields, files

    @staticmethod
    def _data(body: object, stage: ResponseStage, task_id: str | None = None) -> JsonObject:
        if not isinstance(body, dict):
            raise H3ResponseError(stage, task_id=task_id)
        data = body.get('data', body)
        if not isinstance(data, dict):
            raise H3ResponseError(stage, task_id=task_id)
        return data

    def _output_path(self, value: object, task_id: str) -> str:
        if not isinstance(value, str):
            raise H3ResponseError('h3_result', task_id=task_id)
        base, target = urlsplit(self._base_url), urlsplit(value)
        if target.scheme or target.netloc:
            if target.scheme != base.scheme or target.netloc != base.netloc:
                raise H3ResponseError('h3_result', task_id=task_id)
        if target.path != '/api/v1/output' or target.fragment or not target.query:
            raise H3ResponseError('h3_result', task_id=task_id)
        return target.path + ('?' + target.query if target.query else '')

    async def generate(self, shot: JsonObject, character_inputs: list[JsonObject], *,
                       checkpoint: Checkpoint | None = None,
                       resume: JsonObject | None = None) -> JsonObject:
        resume = resume or {}
        task_id = resume.get('taskId')
        if task_id is not None and (not isinstance(task_id, str) or not re.fullmatch(
            r'[A-Za-z0-9_-]{1,128}', task_id
        )):
            raise H3ResponseError('h3_poll')
        compiled = resume.get('compiled')
        fields: dict[str, str] = {}
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        if task_id is None:
            await report(checkpoint, 'preparing')
            reference_plan(shot, character_inputs)
            shot, character_inputs = await prepare_images(shot, character_inputs, self._asset_store)
            plan = reference_plan(shot, character_inputs)
            # Multipart requires actual bytes. Fail before an optional paid text expansion.
            for item in plan['images']:
                self._image_bytes(item['url'])
            if compiled is None:
                if self._prompt_mode == 'context-ir':
                    compiled = compile_chinese_intent(shot, character_inputs)
                else:
                    if self._prompt_writer is None:
                        raise RuntimeError('H3_PROMPT_WRITER_REQUIRED')
                    await report(checkpoint, 'expanding')
                    compiled = await self._prompt_writer.write(shot, character_inputs)
            elif (not isinstance(compiled, dict)
                  or text_metadata(compiled.get('plan')) != text_metadata(plan)):
                raise RuntimeError('H3_REFERENCE_MODE_CONFLICT')
            # Checkpoints intentionally exclude image bytes and signed URLs. Reload them
            # from the saved shot while retaining the already compiled prompt.
            compiled = {**compiled, 'plan': plan,
                        'execution': self._execution(compiled['execution'])}
            fields, files = self._submission(shot, compiled)
            compiled['submittedPrompt'] = fields['prompt']
            await report(checkpoint, 'prepared', {'compiled': text_metadata(compiled)})
        if not isinstance(compiled, dict):
            raise H3ResponseError('h3_poll' if task_id else 'h3_submit', task_id=task_id)
        stage: ResponseStage = 'h3_poll' if task_id else 'h3_submit'
        video_url = ''
        async with httpx.AsyncClient(base_url=self._base_url,
                                     headers={'Authorization': f'Bearer {self._api_key}'},
                                     timeout=self._timeout, transport=self._transport,
                                     follow_redirects=False) as client:
            try:
                if task_id is None:
                    await report(checkpoint, 'submitting')
                    response = await client.post(
                        '/api/v1/jobs', files=[
                            *((name, (None, value)) for name, value in fields.items()), *files,
                        ],
                    )
                    if response.is_redirect:
                        raise H3ResponseError('h3_submit')
                    response.raise_for_status()
                    if response.status_code != 202:
                        raise H3ResponseError('h3_submit')
                    task = self._data(response.json(), 'h3_submit')
                    task_id = task.get('prompt_id')
                    if not isinstance(task_id, str) or not re.fullmatch(
                        r'[A-Za-z0-9_-]{1,128}', task_id
                    ):
                        raise H3ResponseError('h3_submit')
                    await report(checkpoint, 'polling', {'taskId': task_id})
                stage = 'h3_poll'
                deadline = time.monotonic() + self._timeout
                while True:
                    response = await client.get(f'/api/v1/jobs/{task_id}')
                    if response.is_redirect:
                        raise H3ResponseError('h3_poll', task_id=task_id)
                    response.raise_for_status()
                    result = self._data(response.json(), 'h3_poll', task_id)
                    status = result.get('status')
                    if result.get('terminal') is True:
                        if status == 'error' and result.get('succeeded') is False:
                            raise H3TaskError('failed', task_id)
                        if status != 'completed' or result.get('succeeded') is not True:
                            raise H3ResponseError('h3_poll', task_id=task_id)
                        break
                    if status not in {'accepted', 'queued', 'running'}:
                        raise H3ResponseError('h3_poll', 'unknown_status', task_id)
                    if time.monotonic() >= deadline:
                        raise H3ResponseError('h3_poll', 'timeout', task_id)
                    await asyncio.sleep(self._poll_interval)
                stage = 'h3_result'
                outputs = result.get('outputs')
                if not isinstance(outputs, list) or not outputs or not isinstance(outputs[0], dict):
                    raise H3ResponseError('h3_result', task_id=task_id)
                video_url = self._output_path(outputs[0].get('download_url'), task_id)
                await report(checkpoint, 'downloading')
                response = await client.get(video_url)
                if response.is_redirect:
                    raise H3ResponseError('h3_result', task_id=task_id)
                response.raise_for_status()
                if not response.content or not response.headers.get(
                    'content-type', ''
                ).lower().startswith(('video/', 'application/octet-stream')):
                    raise H3ResponseError('h3_result', task_id=task_id)
            except httpx.HTTPError as error:
                raise H3RequestError(error, stage, task_id) from error
            except (ValueError, KeyError, TypeError) as error:
                raise H3ResponseError(stage, task_id=task_id) from error
        asset: JsonObject = {
            'id': f"visual-{shot['id']}-{task_id}", 'shotId': shot['id'],
            'type': 'dynamic-video', 'mediaType': 'video', 'provider': 'minimax',
            'modelVersion': self._model, 'requestReference': task_id,
            'sourceUrl': self._base_url + video_url, 'bytes': len(response.content),
            'durationSec': compiled['plan']['durationSec'],
            'generationMode': compiled['plan']['mode'],
            'h3PromptMode': self._prompt_mode, 'promptExecution': compiled['execution'],
            'h3Prompt': compiled.get('submittedPrompt', compiled['prompt']),
            'referenceCharacterIds': [str(item['id']) for item in character_inputs],
            'fallback': False,
        }
        if self._asset_store is not None:
            object_key = f"videos/{shot['id']}/{task_id}.mp4"
            await self._asset_store.put_bytes(
                object_key=object_key, content=response.content, content_type='video/mp4',
            )
            asset['objectKey'] = object_key
        return asset
