from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, File, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from comicflow.api.audio import audio_router
from comicflow.api.characters import character_router
from comicflow.api.composition import composition_router
from comicflow.api.model_registry import registry_router
from comicflow.api.schemas import (
    CreateProjectRequest,
    MediaProviderConfigRequest,
    TextProviderConfigRequest,
    VersionedRequest,
)
from comicflow.api.story_scripts import story_script_router
from comicflow.api.video import video_router
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.identity.magic_link import MagicLinkService
from comicflow.identity.request import current_user_id
from comicflow.infrastructure.database import (
    SqlAlchemyCharacterRepository,
    SqlAlchemyProjectRepository,
    create_session_factory,
)
from comicflow.infrastructure.generation_state import RedisGenerationStateStore
from comicflow.infrastructure.memory import Runtime
from comicflow.infrastructure.runtime_scope import RuntimeScope
from comicflow.observability.metrics import MetricsRegistry
from comicflow.production.interfaces import DynamicVisualProvider
from comicflow.production.pipeline import ProductionPipeline
from comicflow.providers.async_visual import AsyncVisualProvider
from comicflow.providers.audio import LipSyncHttpProvider, TtsHttpProvider
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.config import ProviderConfig, ProviderMode, select_provider_mode
from comicflow.providers.doubao_text import DoubaoTextProvider
from comicflow.providers.error_mapping import map_provider_error
from comicflow.providers.ffmpeg import FfmpegCompositionProvider
from comicflow.providers.media_config import build_media_provider
from comicflow.providers.mock import MockTextProvider
from comicflow.providers.mock_media import (
    MockCompositionProvider,
    MockDynamicVisualProvider,
    MockLipSyncProvider,
    MockModerationProvider,
    MockTtsProvider,
)
from comicflow.providers.model_registry import ModelRegistry, SecretCipher, SqlRegistryRepository
from comicflow.providers.model_selection import selected_image_runtime, selected_runtime
from comicflow.providers.moderation import ModerationHttpProvider
from comicflow.providers.runtime_config import ProviderConfigStore
from comicflow.providers.s3 import create_optional_asset_store
from comicflow.providers.text_errors import TextRequestError
from comicflow.providers.wanx_image import BailianImageProvider

ERROR_STATUS = {
    'RESOURCE_NOT_FOUND': 404,
    'RESOURCE_FILE_MISSING': 404,
    'RESOURCE_FILE_UNTRACKED': 409,
    'RESOURCE_STORAGE_UNAVAILABLE': 503,
    "MODEL_CONFIG_CONFLICT": 409,
    "MODEL_CONNECTION_TEST_BUSY": 409,
    "MODEL_CONFIG_IN_USE": 409,
    "MODEL_CONFIG_NOT_FOUND": 404,
    "MODEL_CONFIG_KEY_INVALID": 503,
    "MODEL_CONFIG_STORAGE_UNAVAILABLE": 503,
    "PROJECT_NOT_FOUND": 404,
    "STORY_TOO_SHORT": 400,
    "STORY_TEXT_REQUIRED": 409,
    "STORY_TEXT_INVALID": 400,
    "DURATION_OUT_OF_RANGE": 400,
    "MODERATION_BLOCKED": 422,
    "MODERATION_REVIEW_REQUIRED": 409,
    "INSUFFICIENT_CREDIT": 409,
    "CHARACTER_NOT_FOUND": 404,
    "CHARACTER_ACCESS_DENIED": 403,
    "CHARACTER_FIELDS_REQUIRED": 400,
    "CHARACTER_VERSION_CONFLICT": 409,
    "CHARACTER_PROMPT_PROVIDER_REQUIRED": 409,
    "CHARACTER_PROMPT_INVALID": 502,
    "PROJECT_ACCESS_DENIED": 403,
    "AUTH_REQUIRED": 401,
    "JOB_NOT_FOUND": 404,
    "JOB_NOT_CANCELLABLE": 409,
    "VERSION_CONFLICT": 409,
    "PREFLIGHT_STALE": 409,
    'VIDEO_JOB_ACTIVE': 409,
    'VIDEO_JOB_AWAITING_ADOPTION': 409,
    'VIDEO_JOB_BUSY': 409,
    'VIDEO_JOB_CONFLICT': 409,
    'VIDEO_JOB_CONFIG_CHANGED': 409,
    'VIDEO_JOB_RESULT_CANDIDATE': 409,
    'VIDEO_JOB_NOT_ADOPTABLE': 409,
    'VIDEO_JOB_CANDIDATE_STALE': 409,
    'VIDEO_JOB_CANDIDATE_MISSING': 409,
    'VIDEO_SUBMISSION_UNKNOWN': 409,
    'VIDEO_JOB_NOT_FOUND': 404,
    'VIDEO_JOB_STORAGE_UNAVAILABLE': 503,
    'IMAGE_JOB_STORAGE_UNAVAILABLE': 503,
    'IMAGE_JOB_NOT_FOUND': 404,
    'IMAGE_JOB_ACTIVE': 409,
    'IMAGE_JOB_BUSY': 409,
    'IMAGE_JOB_CONFLICT': 409,
    'IMAGE_SUBMISSION_UNKNOWN': 409,
    'IMAGE_JOB_NOT_RECOVERABLE': 409,
    "EXPORT_NOT_READY": 409,
    "PROVIDER_NOT_CONFIGURED": 409,
    "PROVIDER_AUTH_FAILED": 401,
    "PROVIDER_RATE_LIMITED": 429,
    "PROVIDER_REQUEST_INVALID": 400,
    "PROVIDER_TIMEOUT": 504,
    "PROVIDER_UNAVAILABLE": 503,
    "IMAGE_MODEL_UNSUPPORTED": 400,
    "IMAGE_REQUEST_INVALID": 400,
    "IMAGE_RATE_LIMITED": 429,
    "IMAGE_QUOTA_EXHAUSTED": 409,
    "IMAGE_CONTENT_REJECTED": 422,
    "IMAGE_DOWNLOAD_FAILED": 502,
    "IMAGE_EDIT_UNSUPPORTED": 400,
    "IMAGE_EDIT_SOURCE_UNREADABLE": 409,
    "IMAGE_EDIT_SOURCE_INVALID": 400,
    "PROVIDER_INVALID_RESPONSE": 502,
    "PROVIDER_SCRIPT_LANGUAGE_INVALID": 502,
    "H3_PROMPT_WRITER_REQUIRED": 409,
    "H3_SKILL_UNAVAILABLE": 503,
    "H3_PROMPT_INVALID": 502,
    "REFERENCE_IMAGE_PROVIDER_REQUIRED": 409,
    "REFERENCE_CANDIDATE_NOT_FOUND": 404,
    "REFERENCE_CANDIDATE_REQUIRED": 409,
    "REFERENCE_CANDIDATE_VERSION_CONFLICT": 409,
    "REFERENCE_IMAGE_NOT_APPROVED": 409,
    "REFERENCE_VIEWS_PARTIAL": 502,
    "WORKFLOW_MODE_MISMATCH": 409,
    "GENERATION_IN_PROGRESS": 409,
    "SESSION_ACTION_INVALID": 400,
    "REFERENCE_IMAGE_TYPE_INVALID": 400,
    "REFERENCE_IMAGE_SIZE_INVALID": 413,
    "ASSETS_INCOMPLETE": 409,
    "PROVIDER_CREDENTIALS_REQUIRED": 409,
    "VIDEO_FIRST_FRAME_REQUIRED": 409,
    "VIDEO_FIRST_FRAME_UNREACHABLE": 409,
    "VIDEO_FIRST_FRAME_UNREADABLE": 502,
    "VIDEO_MODE_UNSUPPORTED": 400,
    "VIDEO_DURATION_INVALID": 400,
    "VIDEO_RESOLUTION_INVALID": 400,
    "VIDEO_REQUEST_INVALID": 400,
    "VIDEO_PROMPT_TOO_LONG": 400,
    "VIDEO_PROMPT_REQUIRED": 400,
    "VIDEO_QUOTA_EXHAUSTED": 409,
    "VIDEO_RATE_LIMITED": 429,
    "VIDEO_TASK_CANCELLED": 409,
    "VIDEO_GENERATION_FAILED": 502,
    "VIDEO_CONTENT_REJECTED": 422,
    "CASCADE_FRAME_MISSING": 409,
    "H3_REFERENCE_UNREADABLE": 409,
    "H3_REFERENCE_UNREACHABLE": 409,
    "H3_REFERENCE_TOO_LARGE": 413,
}


def create_configured_runtime() -> Runtime:
    """Build the configured runtime; memory is an explicit local-only option."""
    import os

    runtime_mode = os.getenv("COMICFLOW_RUNTIME", "postgresql").lower()
    if runtime_mode.lower() == "memory":
        from comicflow.infrastructure.memory import create_memory_runtime

        redis_url = os.getenv("REDIS_URL")
        state_store = RedisGenerationStateStore(redis_url) if redis_url else None
        return create_memory_runtime(generation_state_store=state_store)
    if runtime_mode != "postgresql":
        raise ValueError(f"unsupported COMICFLOW_RUNTIME: {runtime_mode}")

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://comicflow:comicflow_dev_only@127.0.0.1:15432/comicflow",
    )
    _engine, sessions = create_session_factory(database_url)
    asset_store = create_optional_asset_store()
    composition_provider = (
        FfmpegCompositionProvider(asset_store=asset_store)
        if os.getenv("COMICFLOW_COMPOSITION_PROVIDER", "mock").lower() == "ffmpeg"
        else MockCompositionProvider()
    )
    provider_config = ProviderConfig.from_env(os.environ)
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    generation_state_store = RedisGenerationStateStore(redis_url)
    runtime_provider_store = ProviderConfigStore()
    use_real = select_provider_mode(provider_config) is ProviderMode.REAL
    if provider_config.text_api_key:
        runtime_provider_store.configure_text(
            {
                "provider": provider_config.text_provider,
                "baseUrl": provider_config.text_base_url,
                "model": os.getenv(
                    'TEXT_PROVIDER_MODEL',
                    'Doubao-Seed-2.1-turbo' if provider_config.text_provider == 'doubao'
                    else 'qwen-plus',
                ),
                "timeoutMs": int(os.getenv('TEXT_PROVIDER_TIMEOUT_MS', '120000')),
                "enabled": use_real,
            },
            provider_config.text_api_key,
        )
    # Media capabilities (visual/tts/lipsync/moderation) stay on Mock while the
    # text capability uses the real provider when MEDIA_PROVIDER_MODE=mock.
    media_real = use_real and os.getenv("MEDIA_PROVIDER_MODE", "").lower() != "mock"
    # TTS can go real independently (TTS_PROVIDER_MODE=real) while visuals stay Mock.
    tts_real = media_real or os.getenv("TTS_PROVIDER_MODE", "").lower() == "real"
    # Visuals can use real wanx text-to-image independently (VISUAL_PROVIDER_MODE=real).
    visual_real = media_real or os.getenv("VISUAL_PROVIDER_MODE", "").lower() == "real"
    # MiniMax H3 video generation can be enabled independently.
    use_minimax_h3 = os.getenv("USE_MINIMAX_H3", "").lower() == "true"
    # Keep media credentials independent from a Doubao text key. Images/audio
    # still use the Bailian key unless their own capability config overrides it.
    api_key = provider_config.bailian_api_key or ""
    image_profile = {
        'provider': 'bailian-image',
        'baseUrl': os.getenv('IMAGE_PROVIDER_BASE_URL', 'https://dashscope.aliyuncs.com/api/v1'),
        'model': os.getenv('IMAGE_PROVIDER_MODEL', 'wanx2.1-t2i-plus'),
        'timeoutMs': int(os.getenv('IMAGE_PROVIDER_TIMEOUT_MS', '180000')),
        'enabled': os.getenv(
            'IMAGE_PROVIDER_MODE', 'real' if visual_real else 'disabled'
        ) == 'real',
        'size': os.getenv('IMAGE_PROVIDER_SIZE', '720*1280'),
        'imageProtocol': os.getenv('IMAGE_PROVIDER_PROTOCOL', 'auto'),
        'requestPath': os.getenv('IMAGE_PROVIDER_SUBMIT_PATH', ''),
        'statusPath': os.getenv('IMAGE_PROVIDER_QUERY_PATH', ''),
    }
    image_key = os.getenv('IMAGE_PROVIDER_API_KEY', api_key)
    runtime_provider_store.configure_media('image', image_profile, image_key)
    reference_image_provider = build_media_provider(
        'image', {**image_profile, 'apiKey': image_key}, asset_store
    )

    # Select dynamic visual provider
    dynamic_visual_provider: DynamicVisualProvider
    if use_minimax_h3:
        # Use MiniMax H3 for video generation
        from comicflow.providers.minimax_h3 import MinimaxH3Provider

        minimax_api_key = os.getenv("MINIMAX_API_KEY")
        if not minimax_api_key:
            raise RuntimeError("MINIMAX_API_KEY is required when USE_MINIMAX_H3=true")

        dynamic_visual_provider = MinimaxH3Provider(
            api_key=minimax_api_key,
            base_url=os.getenv("MINIMAX_BASE_URL", "https://cp.compshare.cn"),
            model=os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-H3"),
            submit_path=os.getenv("MINIMAX_SUBMIT_PATH", "/minimax/v2/video_generation"),
            query_path=os.getenv(
                "MINIMAX_QUERY_PATH", "/minimax/v2/query/video_generation/{task_id}"
            ),
            resolution=os.getenv("MINIMAX_VIDEO_RESOLUTION", "768P"),
            prompt_mode=os.getenv("MINIMAX_PROMPT_MODE", "local-skill"),
            timeout_seconds=float(os.getenv("MINIMAX_TIMEOUT_SECONDS", "600")),
            poll_interval_seconds=float(os.getenv("MINIMAX_POLL_INTERVAL_SECONDS", "5")),
            asset_store=asset_store,
        )
    elif visual_real:
        # Use Bailian wanx for image generation
        dynamic_visual_provider = BailianImageProvider(
            api_key=api_key,
            base_url=os.getenv(
                "VISUAL_PROVIDER_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
            ),
            model=os.getenv("VISUAL_PROVIDER_MODEL", "wanx2.1-t2i-plus"),
            size=os.getenv("VISUAL_IMAGE_SIZE", "720*1280"),
            asset_store=asset_store,
        )
    elif media_real:
        # Use async video provider
        dynamic_visual_provider = AsyncVisualProvider(
            api_key=api_key,
            base_url=os.getenv("VISUAL_PROVIDER_BASE_URL", provider_config.base_url),
            model=os.getenv("VISUAL_PROVIDER_MODEL", "wan-video-v1"),
        )
    else:
        # Mock provider
        dynamic_visual_provider = MockDynamicVisualProvider()

    runtime_provider_store.configure_media('video', {
        'provider': 'compshare-h3', 'enabled': use_minimax_h3,
        'baseUrl': os.getenv('MINIMAX_BASE_URL', 'https://cp.compshare.cn'),
        'model': os.getenv('MINIMAX_VIDEO_MODEL', 'MiniMax-H3'),
        'timeoutMs': int(float(os.getenv('MINIMAX_TIMEOUT_SECONDS', '600')) * 1000),
        'resolution': os.getenv('MINIMAX_VIDEO_RESOLUTION', '768P'),
        'h3PromptMode': os.getenv('MINIMAX_PROMPT_MODE', 'local-skill'),
        'submitPath': os.getenv('MINIMAX_SUBMIT_PATH', '/minimax/v2/video_generation'),
        'queryPath': os.getenv(
            'MINIMAX_QUERY_PATH', '/minimax/v2/query/video_generation/{task_id}'
        ),
    }, os.getenv('MINIMAX_API_KEY', ''))

    runtime = Runtime(
        pipeline=ProductionPipeline(
            repository=SqlAlchemyProjectRepository(sessions),
            character_repository=SqlAlchemyCharacterRepository(sessions),
            text_provider=(
                (
                    DoubaoTextProvider(
                        api_key=provider_config.text_api_key or "",
                        base_url=provider_config.text_base_url,
                        model=os.getenv('TEXT_PROVIDER_MODEL', 'Doubao-Seed-2.1-turbo'),
                        timeout_seconds=(
                            float(os.getenv("TEXT_PROVIDER_TIMEOUT_MS", "120000")) / 1000
                        ),
                    )
                    if provider_config.text_provider == 'doubao'
                    else BailianTextProvider(
                        api_key=provider_config.text_api_key or "",
                        base_url=provider_config.text_base_url,
                        model=os.getenv('TEXT_PROVIDER_MODEL', 'qwen-plus'),
                        timeout_seconds=(
                            float(os.getenv("TEXT_PROVIDER_TIMEOUT_MS", "120000")) / 1000
                        ),
                    )
                )
                if use_real
                else MockTextProvider()
            ),
            dynamic_visual_provider=dynamic_visual_provider,
            reference_image_provider=reference_image_provider,
            tts_provider=(
                TtsHttpProvider(
                    api_key=api_key,
                    base_url=os.getenv(
                        "TTS_PROVIDER_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
                    ),
                    model=os.getenv("TTS_PROVIDER_MODEL", "qwen3-tts-flash"),
                    voice=os.getenv("TTS_VOICE", "Cherry"),
                    asset_store=asset_store,
                )
                if tts_real
                else MockTtsProvider()
            ),
            lip_sync_provider=(
                LipSyncHttpProvider(
                    api_key=api_key,
                    base_url=os.getenv("LIPSYNC_PROVIDER_BASE_URL", provider_config.base_url),
                )
                if media_real
                else MockLipSyncProvider()
            ),
            composition_provider=composition_provider,
            moderation_provider=(
                ModerationHttpProvider(
                    api_key=api_key,
                    base_url=os.getenv("MODERATION_PROVIDER_BASE_URL", provider_config.base_url),
                )
                if media_real
                else MockModerationProvider()
            ),
            asset_store=asset_store,
            generation_state_store=generation_state_store,
        ),
        provider_config_store=runtime_provider_store,
        generation_state_store=generation_state_store,
        model_registry=ModelRegistry(SqlRegistryRepository(sessions), SecretCipher.configured()),
    )
    return runtime


def create_app(runtime: Runtime | None = None) -> FastAPI:
    base_runtime = runtime or create_configured_runtime()
    active_runtime = RuntimeScope(base_runtime)
    identity = MagicLinkService()
    metrics = MetricsRegistry()
    app = FastAPI(title="ComicFlow API", version="0.2.0")
    app.include_router(registry_router(
        base_runtime.model_registry, base_runtime.provider_config_store,
    ))

    @app.middleware('http')
    async def bind_model_snapshot(request: Request, call_next: Any) -> Any:
        if request.url.path in {'/health', '/metrics'} or request.url.path.startswith(
            '/api/model-registry'
        ):
            return await call_next(request)
        # Reading/recovering a saved job must survive changes to current bindings.
        # Execution resolves the saved revision in the worker, never here.
        if request.url.path.endswith('/reference-board/approve'):
            return await call_next(request)
        if '/image-jobs' in request.url.path and '/characters/' not in request.url.path:
            return await call_next(request)
        if ('/video-jobs' in request.url.path and '/shots/' not in request.url.path
                and not request.url.path.endswith('/adopt')):
            return await call_next(request)
        try:
            if request.url.path.startswith('/api/provider-config') and request.method != 'GET':
                if (await base_runtime.model_registry.view())['bindings']:
                    return JSONResponse(
                        status_code=409, content={'error': 'MODEL_REGISTRY_MANAGED'},
                    )
                return await call_next(request)
            selected = (await selected_image_runtime(base_runtime)
                        if '/image-jobs' in request.url.path
                        else await selected_runtime(base_runtime))
        except DomainError as error:
            return JSONResponse(status_code=ERROR_STATUS.get(error.code, 400),
                                content={'error': error.code})
        token = active_runtime.current.set(selected)
        try:
            return await call_next(request)
        finally:
            active_runtime.current.reset(token)

    async def require_project_access(project_id: str, user_id: str | None) -> None:
        await active_runtime.pipeline.get_snapshot(project_id, user_id=user_id)

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, error: DomainError) -> JSONResponse:
        if error.code == "MODERATION_BLOCKED":
            metrics.increment("moderation_blocked_total")
        if error.code in {"EXPORT_PACKAGE_INCOMPLETE", "FFMPEG_COMPOSITION_FAILED"}:
            metrics.increment("export_failure_total")
        return JSONResponse(
            status_code=ERROR_STATUS.get(error.code, 400),
            content={"error": error.code, **error.detail},
        )

    from sqlalchemy.exc import SQLAlchemyError

    @app.exception_handler(SQLAlchemyError)
    async def handle_storage_error(_request: Request, _error: SQLAlchemyError) -> JSONResponse:
        code = ('IMAGE_JOB_STORAGE_UNAVAILABLE' if any(part in _request.url.path for part in
                ('/image-jobs', '/reference-candidate', '/reference-views'))
                else 'VIDEO_JOB_STORAGE_UNAVAILABLE')
        return JSONResponse(status_code=503, content={'error': code})

    @app.get("/health")
    async def health() -> dict[str, str]:
        metrics.increment("health_checks_total")
        return {"status": "ok"}

    @app.get("/metrics")
    async def read_metrics() -> dict[str, int]:
        return metrics.snapshot()

    @app.get("/api/provider-config")
    async def get_provider_config() -> dict[str, object]:
        result: dict[str, object] = {
            "text": active_runtime.provider_config_store.masked_text(),
            "image": active_runtime.provider_config_store.masked_media('image'),
            "video": active_runtime.provider_config_store.masked_media('video'),
            "h3Prompt": {'binding': 'text', 'skill': 'h3-prompt-writing', 'required': True},
            "scope": 'api-process',
            "profiles": active_runtime.provider_config_store.profile_views(),
            "runtime": active_runtime.pipeline.get_provider_status(),
        }
        catalog = await base_runtime.model_registry.view()
        if catalog['bindings']:
            from comicflow.providers.model_protocols import PROTOCOLS
            for capability, usage in (('text', 'story'), ('image', 'image'), ('video', 'video')):
                identifier = catalog['bindings'].get(usage)
                if identifier:
                    model = next(m for m in catalog['models'] if m['id'] == identifier)
                    connection = next(c for c in catalog['connections']
                                      if c['id'] == model['connectionId'])
                    result[capability] = {
                        **model['config'], 'provider': PROTOCOLS[model['protocol']]['provider'],
                        'model': model['model'], 'baseUrl': connection['baseUrl'],
                        'enabled': model['enabled'], 'configured': connection['configured'],
                        'apiKeyMasked': '********' if connection['configured'] else '',
                    }
            result['scope'] = catalog['scope']
        return result

    def profile_key(profile: dict[str, Any], old: dict[str, Any], key: str | None) -> str:
        from urllib.parse import urlparse
        if key:
            return key
        if old.get('apiKey') and (
            old.get('provider') != profile.get('provider')
            or urlparse(str(old.get('baseUrl', ''))).scheme
            != urlparse(str(profile.get('baseUrl', ''))).scheme
            or urlparse(str(old.get('baseUrl', ''))).netloc
            != urlparse(str(profile.get('baseUrl', ''))).netloc
        ):
            raise DomainError('PROVIDER_CREDENTIALS_REQUIRED')
        return str(old.get('apiKey') or '')

    def require_profile_target(capability: str, slot: str) -> None:
        if capability not in {'text', 'image', 'video'} or slot not in {'test', 'production'}:
            raise DomainError('PROVIDER_CONFIG_INVALID')

    def construct_profile(capability: str, profile: dict[str, Any]) -> Any:
        if capability == 'text':
            from urllib.parse import urlparse
            url = urlparse(str(profile.get('baseUrl', '')))
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username:
                raise DomainError('PROVIDER_CONFIG_INVALID')
            if not profile.get('enabled'):
                return MockTextProvider()
            if not profile.get('apiKey'):
                raise DomainError('PROVIDER_NOT_CONFIGURED')
            text_provider = profile['provider']
            provider_class = (
                DoubaoTextProvider if text_provider == 'doubao' else BailianTextProvider
            )
            return provider_class(
                api_key=profile['apiKey'], base_url=profile['baseUrl'], model=profile['model'],
                timeout_seconds=profile['timeoutMs'] / 1000,
            )
        try:
            return build_media_provider(capability, profile, active_runtime.pipeline._asset_store)
        except RuntimeError as error:
            raise DomainError(str(error)) from error

    def apply_profile(capability: str, provider: Any) -> None:
        if capability == 'text':
            active_runtime.pipeline.set_text_provider(provider)
        elif capability == 'image':
            active_runtime.pipeline.set_reference_image_provider(provider)
        else:
            active_runtime.pipeline.set_video_provider(provider)

    @app.put('/api/provider-config/profiles/{capability}/{slot}')
    async def save_profile(capability: str, slot: str, payload: dict[str, Any]) -> dict[str, Any]:
        require_profile_target(capability, slot)
        try:
            parsed = (TextProviderConfigRequest.model_validate(payload) if capability == 'text'
                      else MediaProviderConfigRequest.model_validate(payload))
        except ValidationError as error:
            # Log validation errors without exposing credentials
            import logging
            logging.error(
                "Provider config validation failed for %s/%s: %s errors",
                capability, slot, error.error_count(),
            )
            for err in error.errors():
                logging.error(f"  - {err['loc']}: {err['msg']} (type: {err['type']})")
            # Do not include Pydantic input values: they may contain submitted credentials.
            raise DomainError('PROVIDER_CONFIG_INVALID') from error
        profile = parsed.model_dump(by_alias=True, exclude={'api_key'}, exclude_none=True)
        store = active_runtime.provider_config_store
        key = profile_key(profile, store.get_profile(capability, slot), parsed.api_key)
        provider = construct_profile(capability, {**profile, 'apiKey': key})
        if store.active_slot(capability) == slot:
            apply_profile(capability, provider)
        store.configure_profile(capability, slot, profile, key)
        return store.masked_profile(capability, slot)

    @app.post('/api/provider-config/profiles/{capability}/{slot}/activate')
    async def activate_profile(capability: str, slot: str) -> dict[str, Any]:
        require_profile_target(capability, slot)
        store = active_runtime.provider_config_store
        profile = store.get_profile(capability, slot)
        if not profile.get('provider'):
            raise DomainError('PROVIDER_NOT_CONFIGURED')
        provider = construct_profile(capability, profile)
        apply_profile(capability, provider)
        store.activate(capability, slot)
        return {'active': slot, 'profile': store.masked_profile(capability, slot)}

    @app.delete('/api/provider-config/profiles/{capability}/{slot}', status_code=204)
    async def clear_profile(capability: str, slot: str) -> None:
        require_profile_target(capability, slot)
        store = active_runtime.provider_config_store
        if store.active_slot(capability) == slot:
            apply_profile(capability, MockTextProvider() if capability == 'text' else (
                None if capability == 'image' else MockDynamicVisualProvider()
            ))
        store.clear_profile(capability, slot)

    @app.put("/api/provider-config/text")
    async def save_text_provider_config(payload: TextProviderConfigRequest) -> dict[str, object]:
        profile = payload.model_dump(by_alias=True, exclude={"api_key"}, exclude_none=True)
        profile_key(profile, active_runtime.provider_config_store.get_text(), payload.api_key)
        if payload.enabled:
            key = payload.api_key or active_runtime.provider_config_store.get_text().get("apiKey")
            if not isinstance(key, str) or not key:
                raise DomainError("PROVIDER_NOT_CONFIGURED")
            provider_class = (
                DoubaoTextProvider if payload.provider == 'doubao' else BailianTextProvider
            )
            active_runtime.pipeline.set_text_provider(
                provider_class(
                    api_key=key,
                    base_url=payload.base_url,
                    model=payload.model,
                    timeout_seconds=payload.timeout_ms / 1000,
                )
            )
        else:
            active_runtime.pipeline.set_text_provider(MockTextProvider())
        active_runtime.provider_config_store.configure_text(profile, payload.api_key)
        return active_runtime.provider_config_store.masked_text()

    @app.put('/api/provider-config/media/{capability}')
    async def save_media_config(
        capability: str, payload: MediaProviderConfigRequest
    ) -> dict[str, object]:
        if capability not in {'image', 'video'}:
            raise DomainError('PROVIDER_CAPABILITY_UNSUPPORTED')
        profile = payload.model_dump(by_alias=True, exclude={'api_key'})
        construct_profile(capability, {**profile, 'enabled': False})
        key = profile_key(
            profile, active_runtime.provider_config_store.get_media(capability), payload.api_key
        )
        try:
            provider = build_media_provider(
                capability, {**profile, 'apiKey': key}, active_runtime.pipeline._asset_store
            )
        except RuntimeError as error:
            raise DomainError(str(error)) from error
        if capability == 'image':
            active_runtime.pipeline.set_reference_image_provider(provider)
        elif provider is not None:
            active_runtime.pipeline.set_video_provider(provider)
        active_runtime.provider_config_store.configure_media(capability, profile, payload.api_key)
        return active_runtime.provider_config_store.masked_media(capability)

    @app.delete('/api/provider-config/media/{capability}', status_code=204)
    async def clear_media_config(capability: str) -> None:
        if capability not in {'image', 'video'}:
            raise DomainError('PROVIDER_CAPABILITY_UNSUPPORTED')
        if capability == 'image':
            active_runtime.pipeline.set_reference_image_provider(None)
        else:
            active_runtime.pipeline.set_video_provider(MockDynamicVisualProvider())
        active_runtime.provider_config_store.clear_media(capability)

    @app.post("/api/provider-config/text/test")
    async def test_text_provider_config() -> dict[str, object]:
        config = active_runtime.provider_config_store.get_text()
        api_key = config.get("apiKey")
        if not isinstance(api_key, str) or not api_key:
            raise DomainError("PROVIDER_NOT_CONFIGURED")
        try:
            provider_class = (
                DoubaoTextProvider if config.get("provider") == "doubao" else BailianTextProvider
            )
            model = await provider_class(
                api_key=api_key,
                base_url=str(config.get("baseUrl", "")),
                model=str(config.get("model", "qwen-plus")),
                timeout_seconds=float(config.get("timeoutMs", 30000)) / 1000,
            ).check_connectivity()
        except TextRequestError as error:
            # Keep the closed-set upstream reason: this gate exists so a refused
            # credential or an unopened model is learned here, not by spending a
            # generation attempt to find out.
            raise DomainError(map_provider_error(str(error)), dict(error.detail)) from error
        except RuntimeError as error:
            raise DomainError(map_provider_error(str(error))) from error
        return {"ok": True, "model": model}

    @app.delete("/api/provider-config/text", status_code=204)
    async def delete_text_provider_config() -> None:
        active_runtime.provider_config_store.clear_text()
        active_runtime.pipeline.set_text_provider(MockTextProvider())

    @app.post("/api/auth/magic-link", response_model=None)
    async def request_magic_link(payload: dict[str, object]) -> Any:
        email = payload.get("email")
        if not isinstance(email, str):
            return JSONResponse(status_code=400, content={"error": "INVALID_EMAIL"})
        try:
            return identity.issue(email)
        except ValueError as error:
            return JSONResponse(status_code=400, content={"error": str(error)})

    @app.post("/api/auth/verify", response_model=None)
    async def verify_magic_link(payload: dict[str, object]) -> Any:
        token = payload.get("token")
        if not isinstance(token, str):
            return JSONResponse(status_code=400, content={"error": "INVALID_MAGIC_LINK"})
        try:
            return identity.verify(token)
        except ValueError as error:
            return JSONResponse(status_code=401, content={"error": str(error)})

    @app.get('/api/visual-styles')
    async def visual_styles() -> dict[str, object]:
        from comicflow.production.visual_styles import style_catalog
        return style_catalog()

    @app.post("/api/projects", status_code=201)
    async def create_project(
        payload: CreateProjectRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        return await active_runtime.pipeline.create_project(
            CreateProject(
                input_type=payload.input_type,
                story=payload.story,
                duration_sec=payload.duration_sec,
                mode=payload.mode,
                style_preset_id=payload.style_preset_id,
            ),
            owner_user_id=x_user_id,
        )

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, object]]:
        return await active_runtime.pipeline.list_projects()

    @app.get('/api/projects/{project_id}/video-resources')
    async def video_resources(
        project_id: str, x_user_id: str | None = Depends(current_user_id),
        kind: Literal['all', 'shot', 'export'] = 'all',
        status: Literal['all', 'current', 'historical', 'candidate', 'stale'] = 'all',
        shot_id: str | None = None, offset: int = Query(default=0, ge=0),
        limit: int = Query(default=24, ge=1, le=100),
    ) -> JSONResponse:
        result = await active_runtime.pipeline.video_resources().list(
            project_id, x_user_id, kind=kind, shot_id=shot_id,
            status=status, offset=offset, limit=limit,
        )
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @app.get('/api/projects/{project_id}/video-resources/{asset_id}/access')
    async def video_resource_access(
        project_id: str, asset_id: str, download: bool = False,
        x_user_id: str | None = Depends(current_user_id),
    ) -> JSONResponse:
        result = await active_runtime.pipeline.video_resources().access(
            project_id, asset_id, x_user_id, download=download,
        )
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @app.post("/api/projects/{project_id}/reference-image")
    async def upload_reference_image(
        project_id: str,
        file: Annotated[UploadFile, File()],
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        content = await file.read()
        return await active_runtime.pipeline.upload_reference_image(
            project_id,
            file.filename or "reference-image",
            file.content_type or "application/octet-stream",
            content,
            x_user_id,
        )

    @app.get("/api/projects/{project_id}")
    async def get_snapshot(
        project_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> dict[str, object]:
        return await active_runtime.pipeline.get_snapshot(project_id, user_id=x_user_id)

    @app.post("/api/projects/{project_id}/duplicate", status_code=201)
    async def duplicate_project(
        project_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await active_runtime.pipeline.duplicate_project(project_id)

    @app.get("/api/projects/{project_id}/generation-session")
    async def generation_session(
        project_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        return await active_runtime.pipeline.get_generation_session(project_id)

    @app.post("/api/projects/{project_id}/generation-session/{action}")
    async def update_generation_session(
        project_id: str, action: str, x_user_id: str | None = Depends(current_user_id)
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        if action == "advance":
            return await active_runtime.pipeline.advance_generation_session(project_id)
        return await active_runtime.pipeline.update_generation_session(project_id, action)

    @app.post("/api/projects/{project_id}/claim")
    async def claim_project(
        project_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> dict[str, object]:
        if not x_user_id:
            raise DomainError("AUTH_REQUIRED")
        return await active_runtime.pipeline.claim_project(project_id, user_id=x_user_id)

    @app.get("/api/projects/{project_id}/credits")
    async def project_credits(
        project_id: str, x_user_id: str | None = Depends(current_user_id)
    ) -> dict[str, object]:
        if not x_user_id:
            raise DomainError("AUTH_REQUIRED")
        return await active_runtime.pipeline.project_credits(project_id, user_id=x_user_id)


    @app.get("/api/projects/{project_id}/events")
    async def project_events(
        project_id: str,
        x_user_id: str | None = Depends(current_user_id),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        await require_project_access(project_id, x_user_id)

        async def stream() -> AsyncIterator[str]:
            deadline = asyncio.get_running_loop().time() + 30
            emissions = 0
            last_progress_payload: str | None = None
            # Progress events use numeric IDs while Redis generation events use
            # stream IDs. A reconnect carrying a numeric progress ID must not
            # replay the entire generation stream from zero.
            stream_cursor: str | None = (
                None if last_event_id and "-" not in last_event_id else (last_event_id or "0")
            )
            try:
                progress_id = int(last_event_id or "0")
            except ValueError:
                progress_id = 0
            while asyncio.get_running_loop().time() < deadline:
                if stream_cursor is not None:
                    generation_events = await active_runtime.generation_state_store.read_events(
                        project_id, last_event_id=stream_cursor
                    )
                    for generation_event in generation_events:
                        stream_cursor = str(generation_event.get("id", stream_cursor))
                        payload = json.dumps(generation_event.get("data", {}), ensure_ascii=False)
                        yield f"id: {stream_cursor}\nevent: generation\ndata: {payload}\n\n"
                snapshot = await active_runtime.pipeline.get_snapshot(project_id, user_id=x_user_id)
                payload = json.dumps(snapshot, ensure_ascii=False)
                jobs = snapshot.get("jobs", [])
                session = snapshot.get("project", {}).get("generationSession", {})
                generation_running = (
                    isinstance(session, dict) and session.get("status") == "running"
                )
                if payload != last_progress_payload:
                    progress_id += 1
                    yield f"id: {progress_id}\nevent: progress\ndata: {payload}\n\n"
                    last_progress_payload = payload
                    emissions += 1
                if emissions >= 1 and not generation_running and (not jobs or all(
                    job.get("status") in {"succeeded", "failed", "cancelled", "stale"}
                    for job in jobs
                )):
                    break
                await asyncio.sleep(0.5)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post('/api/projects/{project_id}/references/{kind}/{target_id}')
    async def generate_project_reference(
        project_id: str, kind: str, target_id: str, payload: VersionedRequest,
        x_user_id: str | None = Depends(current_user_id),
    ) -> dict[str, object]:
        await require_project_access(project_id, x_user_id)
        if kind not in {'characters', 'scenes'}:
            raise DomainError('REFERENCE_KIND_INVALID')
        return await active_runtime.pipeline.generate_project_reference(
            project_id, kind, target_id, expected_version=payload.expected_version
        )

    app.include_router(story_script_router(lambda: active_runtime.pipeline, require_project_access))
    app.include_router(character_router(lambda: active_runtime.pipeline, require_project_access))
    app.include_router(video_router(lambda: active_runtime.pipeline, require_project_access))
    app.include_router(composition_router(lambda: active_runtime.pipeline, require_project_access))
    app.include_router(audio_router(lambda: active_runtime.pipeline, require_project_access))


    return app


app = create_app()
