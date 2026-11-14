"""Test media_config factory for openai-image provider."""

import pytest
from comicflow.providers.media_config import build_media_provider
from comicflow.providers.openai_image import OpenAIImageProvider


def test_media_config_builds_openai_image_provider():
    """Factory builds OpenAIImageProvider when provider is openai-image."""
    profile = {
        "provider": "openai-image",
        "enabled": True,
        "apiKey": "sk-test123",
        "baseUrl": "https://img.yunfei.best",
        "model": "gpt-image-2.5",
        "timeoutMs": 60000,
    }

    provider = build_media_provider("image", profile, asset_store=None)

    assert isinstance(provider, OpenAIImageProvider)
    assert provider._model == "gpt-image-2.5"
    assert provider._base_url == "https://img.yunfei.best"
    assert provider._api_key == "sk-test123"
    assert provider._timeout == 60


def test_media_config_rejects_invalid_capability():
    """Factory rejects openai-image for video capability."""
    profile = {
        "provider": "openai-image",
        "enabled": True,
        "apiKey": "sk-test",
        "baseUrl": "https://api",
        "model": "gpt-image",
        "timeoutMs": 30000,
    }

    with pytest.raises(RuntimeError) as exc_info:
        build_media_provider("video", profile, asset_store=None)

    assert str(exc_info.value) == "PROVIDER_CAPABILITY_UNSUPPORTED"


def test_media_config_openai_image_validates_base_url():
    """Factory validates baseUrl for openai-image provider."""
    profile = {
        "provider": "openai-image",
        "enabled": True,
        "apiKey": "sk-test",
        "baseUrl": "not-a-url",
        "model": "gpt-image",
        "timeoutMs": 30000,
    }

    with pytest.raises(RuntimeError) as exc_info:
        build_media_provider("image", profile, asset_store=None)

    assert str(exc_info.value) == "PROVIDER_CONFIG_INVALID"


def test_media_config_openai_image_requires_api_key():
    """Factory requires apiKey for enabled openai-image provider."""
    profile = {
        "provider": "openai-image",
        "enabled": True,
        "baseUrl": "https://api",
        "model": "gpt-image",
        "timeoutMs": 30000,
    }

    with pytest.raises(RuntimeError) as exc_info:
        build_media_provider("image", profile, asset_store=None)

    assert str(exc_info.value) == "PROVIDER_NOT_CONFIGURED"


def test_media_config_openai_image_disabled_returns_none():
    """Factory returns None when openai-image is disabled."""
    profile = {
        "provider": "openai-image",
        "enabled": False,
        "apiKey": "sk-test",
        "baseUrl": "https://api",
        "model": "gpt-image",
        "timeoutMs": 30000,
    }

    provider = build_media_provider("image", profile, asset_store=None)

    assert provider is None
