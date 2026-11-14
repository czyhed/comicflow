"""Bind a catalog snapshot to a request, without mutating another request's adapters."""

from __future__ import annotations

from copy import copy
from typing import TYPE_CHECKING, Any

from comicflow.domain.errors import DomainError
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.doubao_text import DoubaoTextProvider
from comicflow.providers.media_config import build_media_provider
from comicflow.providers.model_protocols import (
    PROTOCOLS,
    TemplateTransport,
    validate_config,
    validate_endpoint,
)

if TYPE_CHECKING:
    from comicflow.infrastructure.memory import Runtime

METHOD_USAGE = {
    "generate_story_text": "story",
    "stream_story_text": "story",
    "split_script": "script",
    "generate_script": "script",
    "generate_guided_question": "script",
    "generate_detailed_script": "script",
    "generate_character_prompt": "character-prompt",
    "compile_h3_prompt": "video-prompt",
}


class TemplateTextProvider(BailianTextProvider):
    """Template transport preserves standard SSE; custom mappings stay single-response."""


class ModelSelection:
    def __init__(self, snapshot: dict[str, Any], asset_store: Any) -> None:
        self.snapshot, self.asset_store = snapshot, asset_store
        self._cache: dict[str, Any] = {}

    def provider(self, usage: str, fallback: Any) -> Any:
        identifier = self.snapshot["bindings"].get(usage)
        if not identifier:
            return fallback
        if identifier in self._cache:
            return self._cache[identifier]
        model = next(m for m in self.snapshot["models"] if m["id"] == identifier)
        connection = next(
            c for c in self.snapshot["connections"] if c["id"] == model["connectionId"]
        )
        protocol = model["protocol"]
        validate_endpoint(protocol, connection['baseUrl'])
        if not model["enabled"] or not connection["apiKey"]:
            raise DomainError("PROVIDER_NOT_CONFIGURED")
        config = validate_config(protocol, model["config"])
        provider: Any
        profile = {
            **config,
            "provider": PROTOCOLS[protocol]["provider"],
            "model": model["model"],
            "baseUrl": connection["baseUrl"],
            "apiKey": connection["apiKey"],
            "enabled": True,
        }
        if protocol in {"chat-completions", "doubao-chat"}:
            custom = bool(config.get("request") or config.get("responseTextPath"))
            cls = (
                TemplateTextProvider
                if custom
                else (DoubaoTextProvider if protocol == "doubao-chat" else BailianTextProvider)
            )
            provider = cls(
                api_key=connection["apiKey"],
                base_url=connection["baseUrl"],
                model=model["model"],
                timeout_seconds=config["timeoutMs"] / 1000,
                max_retries=0,
                transport=TemplateTransport(config, connection["baseUrl"], connection["apiKey"])
                if custom
                else None,
            )
        else:
            capability = "video" if "video" in PROTOCOLS[protocol]["usages"] else "image"
            provider = build_media_provider(capability, profile, self.asset_store)
            if protocol == "chat-image":
                provider._transport = TemplateTransport(
                    config,
                    connection["baseUrl"],
                    connection["apiKey"],
                )
        self._cache[identifier] = provider
        return provider


class SelectedText:
    def __init__(self, selection: ModelSelection, fallback: Any) -> None:
        self.selection, self.fallback = selection, fallback

    def __getattr__(self, method: str) -> Any:
        provider = self.selection.provider(METHOD_USAGE.get(method, "story"), self.fallback)
        return getattr(provider, method)


class SelectedImages:
    def __init__(self, selection: ModelSelection, fallback: Any) -> None:
        self.selection, self.fallback = selection, fallback

    @property
    def active_provider(self) -> Any:
        return self.selection.provider("image", self.fallback)

    async def generate(self, shot: dict[str, Any], characters: list[dict[str, Any]]) -> Any:
        usage = (
            "image-edit"
            if shot.get("sourceImageUrl") or shot.get("sourceImageObjectKey")
            else "image"
        )
        provider = self.selection.provider(usage, self.fallback)
        if provider is None:
            raise DomainError("REFERENCE_IMAGE_PROVIDER_REQUIRED")
        return await provider.generate(shot, characters)


async def selected_runtime(runtime: Runtime, revision: int | None = None) -> Runtime:
    from comicflow.infrastructure.memory import Runtime

    snapshot = await runtime.model_registry.snapshot(revision)
    if not snapshot["bindings"]:
        return runtime
    selection = ModelSelection(snapshot, runtime.pipeline._asset_store)
    pipeline = copy(runtime.pipeline)
    pipeline._model_config_revision = snapshot["revision"]
    # _refresh_h3_writer mutates its video adapter; clone legacy fallback too.
    pipeline._dynamic_visual_provider = copy(
        selection.provider(
            "video",
            runtime.pipeline._dynamic_visual_provider,
        )
    )
    pipeline.set_text_provider(SelectedText(selection, runtime.pipeline._text_provider))
    if any(key in snapshot["bindings"] for key in ("image", "image-edit")):
        pipeline.set_reference_image_provider(
            SelectedImages(
                selection,
                runtime.pipeline._reference_image_provider,
            )
        )
    return Runtime(
        pipeline=pipeline,
        provider_config_store=runtime.provider_config_store,
        generation_state_store=runtime.generation_state_store,
        model_registry=runtime.model_registry,
    )


async def selected_image_runtime(runtime: Runtime, revision: int | None = None) -> Runtime:
    """Image recovery does not depend on today's video/text bindings."""
    from comicflow.infrastructure.memory import Runtime

    snapshot = await runtime.model_registry.snapshot(revision)
    pipeline = copy(runtime.pipeline)
    pipeline._model_config_revision = snapshot['revision']
    pipeline.set_reference_image_provider(SelectedImages(
        ModelSelection(snapshot, pipeline._asset_store), runtime.pipeline._reference_image_provider,
    ))
    return Runtime(pipeline=pipeline, provider_config_store=runtime.provider_config_store,
        generation_state_store=runtime.generation_state_store,
        model_registry=runtime.model_registry)
