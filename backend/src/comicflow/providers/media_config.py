"""Factories shared by environment startup and the local API console."""

from urllib.parse import urlparse

from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore, DynamicVisualProvider
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from comicflow.providers.mock_media import MockDynamicVisualProvider
from comicflow.providers.openai_image import OpenAIImageProvider
from comicflow.providers.wanx_image import BailianImageProvider, resolve_image_protocol
from comicflow.providers.xiangongyun_h3 import XiangongyunH3Provider


def build_media_provider(
    capability: str, profile: JsonObject, asset_store: AssetStore | None
) -> DynamicVisualProvider | None:
    expected = {
        "image": {"bailian-image", "openai-image"},
        "video": {"compshare-h3", "xiangongyun-h3", "bailian-video"},
    }
    if capability not in expected or profile.get("provider") not in expected[capability]:
        raise RuntimeError("PROVIDER_CAPABILITY_UNSUPPORTED")
    # Clean and validate baseUrl
    base_url = str(profile.get("baseUrl", "")).strip()
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise RuntimeError("PROVIDER_CONFIG_INVALID")
    # Validate requestPath/statusPath only for providers that need them
    if profile.get('provider') in {'bailian-image', 'bailian-video'}:
        for field in ('requestPath', 'statusPath'):
            path = str(profile.get(field) or '')
            if path and (
                not path.startswith('/') or path.startswith('//') or '\\' in path
                or urlparse(path).netloc or urlparse(path).scheme
                or (field == 'statusPath' and '{task_id}' not in path)
            ):
                raise RuntimeError('PROVIDER_CONFIG_INVALID')
    if capability == 'image':
        if profile.get('provider') == 'bailian-image':
            resolve_image_protocol(
                str(profile.get('model', '')), profile.get('imageProtocol', 'auto')
            )
    if not profile.get("enabled"):
        return MockDynamicVisualProvider() if capability == "video" else None
    if not profile.get("apiKey"):
        raise RuntimeError("PROVIDER_NOT_CONFIGURED")
    common = {
        "api_key": profile["apiKey"],
        "base_url": base_url,
        "model": profile["model"],
        "timeout_seconds": profile["timeoutMs"] / 1000,
        "asset_store": asset_store,
    }
    if capability == "image":
        if profile.get('provider') == 'openai-image':
            return OpenAIImageProvider(**common)
        return BailianImageProvider(
            **common, size=profile.get('size', '720*1280'),
            image_protocol=profile.get('imageProtocol', 'auto'),
            submit_path=profile.get('requestPath', ''), query_path=profile.get('statusPath', ''),
        )
    if profile['provider'] == 'bailian-video':
        generation_type = profile.get('generationType', 'i2v')
        if generation_type not in {'i2v', 't2v'} or (
            '-i2v' in profile['model'] and generation_type != 'i2v'
        ) or ('-t2v' in profile['model'] and generation_type != 't2v'):
            raise RuntimeError('VIDEO_MODE_UNSUPPORTED')
        return BailianImageToVideoProvider(
            **common,
            resolution=profile.get('resolution') or '480P',
            generation_type=generation_type,
            submit_path=profile.get('requestPath', ''), query_path=profile.get('statusPath', ''),
        )
    if profile['provider'] == 'xiangongyun-h3':
        return XiangongyunH3Provider(
            **common, resolution=profile.get('resolution') or '0.5P',
            inference_profile=profile.get('inferenceProfile', 'turbo8_av_sol_gpu_te'),
            prompt_mode=profile.get('h3PromptMode', 'context-ir'),
        )
    if (
        "{task_id}" not in profile.get("queryPath", "")
        or not profile.get("submitPath", "").startswith("/")
        or not profile.get("queryPath", "").startswith("/")
    ):
        raise RuntimeError("PROVIDER_CONFIG_INVALID")
    return MinimaxH3Provider(
        **common,
        resolution=profile.get("resolution") or "768P",
        prompt_mode=profile.get('h3PromptMode', 'local-skill'),
        submit_path=profile["submitPath"],
        query_path=profile["queryPath"],
    )
