"""Provider capability split: text real, and per-capability real/mock toggles."""

import pytest
from comicflow.api.app import create_configured_runtime
from comicflow.providers import mock_media
from comicflow.providers.audio import LipSyncHttpProvider, TtsHttpProvider
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.moderation import ModerationHttpProvider
from comicflow.providers.wanx_image import BailianImageProvider


@pytest.fixture(autouse=True)
def _provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMICFLOW_RUNTIME", "postgresql")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("PROVIDER_MODE", "real")
    monkeypatch.setenv("PROVIDER_EVALUATION_GATE", "passed")
    monkeypatch.setenv("BAILIAN_API_KEY", "sk-dummy-not-a-real-key")
    monkeypatch.setenv("BAILIAN_BASE_URL", "https://example.invalid/v1")


def test_media_provider_mode_mock_keeps_text_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_PROVIDER_MODE", "mock")
    pipeline = create_configured_runtime().pipeline
    assert isinstance(pipeline._text_provider, BailianTextProvider)
    assert isinstance(pipeline._dynamic_visual_provider, mock_media.MockDynamicVisualProvider)
    assert isinstance(pipeline._tts_provider, mock_media.MockTtsProvider)
    assert isinstance(pipeline._lip_sync_provider, mock_media.MockLipSyncProvider)
    assert isinstance(pipeline._moderation_provider, mock_media.MockModerationProvider)


def test_media_provider_mode_defaults_to_real_wanx_images(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MEDIA_PROVIDER_MODE", raising=False)
    pipeline = create_configured_runtime().pipeline
    assert isinstance(pipeline._text_provider, BailianTextProvider)
    assert isinstance(pipeline._dynamic_visual_provider, BailianImageProvider)
    assert isinstance(pipeline._tts_provider, TtsHttpProvider)
    assert isinstance(pipeline._lip_sync_provider, LipSyncHttpProvider)
    assert isinstance(pipeline._moderation_provider, ModerationHttpProvider)


def test_visual_real_while_media_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEDIA_PROVIDER_MODE", "mock")
    monkeypatch.setenv("VISUAL_PROVIDER_MODE", "real")
    pipeline = create_configured_runtime().pipeline
    assert isinstance(pipeline._text_provider, BailianTextProvider)
    assert isinstance(pipeline._dynamic_visual_provider, BailianImageProvider)
    assert isinstance(pipeline._tts_provider, mock_media.MockTtsProvider)
    assert isinstance(pipeline._lip_sync_provider, mock_media.MockLipSyncProvider)


def test_unsupported_provider_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "unsupported")
    with pytest.raises(RuntimeError):
        create_configured_runtime()
