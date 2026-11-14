import pytest
from comicflow.providers.config import ProviderConfig, ProviderMode, select_provider_mode


def test_provider_config_defaults_to_mock_without_secret() -> None:
    config = ProviderConfig.from_env({})
    assert config.mode is ProviderMode.MOCK
    assert config.bailian_api_key is None
    assert "secret" not in repr(config).lower()


def test_real_mode_requires_evaluation_gate_and_api_key() -> None:
    with pytest.raises(RuntimeError, match="PROVIDER_EVALUATION_REQUIRED"):
        ProviderConfig.from_env({"PROVIDER_MODE": "real", "BAILIAN_API_KEY": "key"})
    with pytest.raises(RuntimeError, match="BAILIAN_API_KEY_REQUIRED"):
        ProviderConfig.from_env({"PROVIDER_MODE": "real", "PROVIDER_EVALUATION_GATE": "passed"})


def test_selector_returns_mock_until_gate_is_explicitly_passed() -> None:
    config = ProviderConfig.from_env(
        {
            "PROVIDER_MODE": "real",
            "PROVIDER_EVALUATION_GATE": "passed",
            "BAILIAN_API_KEY": "key",
        }
    )
    assert select_provider_mode(config) is ProviderMode.REAL
