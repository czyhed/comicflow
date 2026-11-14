from comicflow.providers.runtime_config import ProviderConfigStore


def test_text_provider_configuration_is_readable_but_key_is_only_masked() -> None:
    store = ProviderConfigStore()
    profile = {
        "provider": "openai-compatible",
        "baseUrl": "https://provider.test/v1",
        "model": "script-v1",
        "timeoutMs": 30000,
        "enabled": True,
    }

    store.configure_text(profile, "secret-key")

    assert store.text_enabled() is True
    assert store.get_text()["apiKey"] == "secret-key"
    assert store.masked_text()["apiKeyMasked"] == "********"
    assert "apiKey" not in store.masked_text()


def test_clearing_text_configuration_disables_provider() -> None:
    store = ProviderConfigStore()
    store.configure_text({"provider": "custom", "enabled": True}, "key")

    store.clear_text()

    assert store.text_enabled() is False
    assert store.masked_text()["configured"] is False
