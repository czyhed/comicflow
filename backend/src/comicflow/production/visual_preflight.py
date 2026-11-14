"""Read-only generation contract shared by preview and every visual submission."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, cast

from comicflow.domain.models import JsonObject
from comicflow.providers.drama_skills import review_shot_speech
from comicflow.providers.error_mapping import map_provider_error
from comicflow.providers.h3_inputs import local_url


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def stable(value: Any) -> Any:
    """Ignore expiring URL signatures only where an immutable object key is present."""
    if isinstance(value, list):
        return [stable(v) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key.lower().endswith('url'):
                object_key = key[:-3] + 'ObjectKey' if key != 'url' else 'objectKey'
                if value.get(object_key):
                    continue
            result[key] = stable(item)
        return result
    return value


def adapter_identity(provider: Any) -> JsonObject:
    # Internal fingerprint input only. No endpoints, credentials or templates in the response.
    identity = {'class': type(provider).__name__, **{
        field: getattr(provider, field, None) for field in (
            '_model', '_resolution', '_prompt_mode', '_base_url', '_submit_path',
            '_query_path', '_api_key', 'generation_type',
        )}}
    # Preserve fingerprints of existing adapters/jobs; only the new protocol adds this field.
    if hasattr(provider, '_inference_profile'):
        identity['_inference_profile'] = provider._inference_profile
    return identity


def display(value: Any) -> Any:
    """Creative fields may contain pasted URLs too; do not echo signed URLs/base64."""
    if isinstance(value, dict):
        return {k: display(v) for k, v in value.items()
                if not k.lower().endswith(('url', 'objectkey', 'apikey'))}
    if isinstance(value, list):
        return [display(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'data:[^\s"<>]+', '[图片数据已隐藏]', value)
        return re.sub(r'https?://[^\s"<>]+', '[链接已隐藏]', value)
    return value


def failed_preflight(code: str, detail: JsonObject | None = None) -> JsonObject:
    return {'ready': False, 'fingerprint': None, 'errors': [code], 'warnings': [],
            'parameters': {}, 'references': [], 'calls': None, 'price': None,
            'model': None, 'prompt': None, 'errorDetail': display(detail or {})}


def _image_keys(value: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().endswith('url') and isinstance(item, str):
                object_key = key[:-3] + 'ObjectKey' if key != 'url' else 'objectKey'
                if value.get(object_key):
                    result[item] = str(value[object_key])
            result.update(_image_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_image_keys(item))
    return result


async def build_preflight(
    provider: Any, text_provider: Any, project: JsonObject, shot: JsonObject,
    characters: list[JsonObject], revision: int, store: Any,
) -> JsonObject:
    preview = getattr(provider, 'prepare_preview', None)
    warnings: list[str] = []
    try:
        if callable(preview):
            compiled = preview(shot, characters)
        else:
            return failed_preflight('VIDEO_PREFLIGHT_UNSUPPORTED')
    except RuntimeError as error:
        return failed_preflight(map_provider_error(str(error)), getattr(error, 'detail', None))

    images = compiled.pop('images')
    if compiled.get('adapter') == 'mock':
        warnings.append('模拟生成不调用模型，不代表真实视频效果。')
    keys = _image_keys([shot, characters])
    errors = []
    speech = review_shot_speech(shot)
    if speech['severity'] == 'p0':
        errors.append('VIDEO_SPEECH_OVER_BUDGET')
    if any(not str(shot.get(key) or '').strip()
           for key in ('actionBefore', 'actionMiddle', 'actionAfter')):
        warnings.append('动作起始、过程或完成状态未全部单独填写，请核对镜头是否停在中间状态。')
    references = []
    for item in images:
        url = item['url']
        key = keys.get(url)
        state = 'unchecked'
        if key and callable(getattr(store, 'exists', None)):
            try:
                state = 'exists' if await store.exists(key) else 'missing'
                if state == 'missing':
                    errors.append('REFERENCE_FILE_MISSING')
            except Exception:
                state = 'unavailable'
                errors.append('REFERENCE_STORAGE_UNAVAILABLE')
        elif not key and not url.startswith('data:') and local_url(url):
            state = 'unreachable'
            errors.append('H3_REFERENCE_UNREACHABLE')
        references.append({**{k: item.get(k) for k in ('label', 'role', 'id', 'name', 'view')},
                           'fileState': state, 'sourceId': digest(key or url)[:16]})
    if images:
        warnings.append('已检查引用结构；文件存在不等于图片有效。像素/格式/大小在提交前校验，外部链接可达性尚未验证。')
    if compiled.get('mode') == 'ref2va' and any(
        item.get('view') == 'continuity-anchor' for item in images
    ):
        warnings.append('上一镜头尾帧作为普通连续性参考，并非严格首帧锁定。')
    if any(not (c.get('referenceBoardUrl') or c.get('referenceImageUrl')
                or c.get('referenceViews')) for c in characters):
        warnings.append('部分角色只有文字设定，未传人物参考图。')
    if not any(item.get('view') == 'scene-anchor' for item in images):
        warnings.append('未提供场景参考图；场景依据文字及已列出的帧或参考素材，不会自动生成背景。')
    if shot.get('visualDescription') or shot.get('cameraMovement'):
        warnings.append('请人工核对画面机位、运镜与动作起终是否一致；本地检查不能判断文字中的空间矛盾。')

    text_model = None
    text_identity = None
    if (compiled.get('calls') or {}).get('text'):
        # Resolve the very same usage selected by compile_h3_prompt, without completing it.
        if hasattr(text_provider, 'selection'):
            text_provider = text_provider.selection.provider('video-prompt', text_provider.fallback)
        text_identity = adapter_identity(text_provider)
        text_model = getattr(text_provider, '_model', None) or type(text_provider).__name__
    fingerprint = digest(stable({
        'compiler': 1, 'projectId': project['id'], 'version': project['version'],
        'shot': shot, 'characters': characters, 'modelRevision': revision,
        'provider': adapter_identity(provider), 'textProvider': text_identity,
        'compiled': compiled,
        'sourceAssets': [{k: a.get(k) for k in
                          ('id', 'shotId', 'valid', 'objectKey', 'lastFrameObjectKey')}
                         for a in project.get('visualAssets', [])
                         if a.get('valid')],
    }))
    return cast(JsonObject, display({
        **compiled, 'ready': not errors, 'fingerprint': fingerprint,
        'errors': list(dict.fromkeys(errors)), 'warnings': warnings,
        'references': references, 'price': None, 'modelConfigRevision': revision,
        'projectVersion': project['version'], 'shotId': shot['id'], 'textModel': text_model,
        'style': project.get('visualStyleProfile'),
        'speech': {key: shot.get(key) or '' for key in ('dialogue', 'narration')},
        'speechReview': speech,
        'camera': {key: shot.get(key) or '' for key in ('visualDescription', 'cameraMovement')},
        'actionStates': {key: shot.get(key) or (shot.get('continuityPlan') or {}).get(key) or ''
                         for key in ('actionBefore', 'actionMiddle', 'actionAfter')},
    }))
