"""The connectivity-test endpoint must report the provider's real state.

This endpoint is the first gate in the acceptance plan, and it had no coverage.
It returned 503 PROVIDER_UNAVAILABLE against a fully healthy provider, which
sent us looking at credentials and networking instead of at the endpoint.
"""

import httpx
import pytest
from comicflow.api.app import create_app, create_configured_runtime
from httpx import ASGITransport, AsyncClient


def _configured_app(monkeypatch: pytest.MonkeyPatch, handler):
    """Build an app whose text provider is configured and transport is stubbed."""
    monkeypatch.setenv("COMICFLOW_RUNTIME", "memory")
    runtime = create_configured_runtime()
    runtime.provider_config_store.configure_text(
        {
            "provider": "bailian",
            "baseUrl": "https://provider.test/v1",
            "model": "qwen-plus",
            "timeoutMs": 30000,
            "enabled": True,
        },
        "secret-key",
    )
    app = create_app(runtime)
    # The endpoint constructs its own provider, so intercept at the httpx layer.
    monkeypatch.setattr(
        "comicflow.api.app.BailianTextProvider.__init__",
        _init_with_transport(httpx.MockTransport(handler)),
    )
    return app


def _init_with_transport(transport: httpx.MockTransport):
    from comicflow.providers.bailian_text import BailianTextProvider

    original = BailianTextProvider.__init__

    def patched(self, **kwargs) -> None:
        kwargs["transport"] = transport
        original(self, **kwargs)

    return patched


async def _post_test(app) -> httpx.Response:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post("/api/provider-config/text/test")


async def test_a_reachable_provider_reports_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reply carries no script content, which used to produce a 503."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen-plus",
                "choices": [{"message": {"content": '{"title":"","scenes":[],"shots":[]}'}}],
            },
        )

    response = await _post_test(_configured_app(monkeypatch, handler))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "model": "qwen-plus"}


async def test_a_rejected_credential_reports_auth_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})

    response = await _post_test(_configured_app(monkeypatch, handler))
    assert response.status_code == 401
    assert response.json()["error"] == "PROVIDER_AUTH_FAILED"


async def test_a_model_that_is_not_open_reports_the_closed_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ark answers 404 ModelNotOpen for a model the account has not activated.

    The generation path already names this reason. The connectivity gate has to
    report the same thing, otherwise the only way to learn it is to spend a
    generation attempt -- which is exactly what happened on 2026-09-14.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {
            "code": "ModelNotOpen", "param": "model",
            "message": "Your account has not activated the model",
        }})

    response = await _post_test(_configured_app(monkeypatch, handler))
    assert response.status_code == 400
    assert response.json() == {
        'error': 'PROVIDER_REQUEST_INVALID', 'stage': 'text_check',
        'upstreamStatus': 404, 'reason': 'model_not_enabled', 'parameter': 'model',
    }


async def test_a_probe_timeout_names_its_own_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    response = await _post_test(_configured_app(monkeypatch, handler))
    assert response.status_code == 504
    assert response.json() == {
        'error': 'PROVIDER_TIMEOUT', 'stage': 'text_check', 'reason': 'timeout',
        'timeoutMs': 30000,
    }


async def test_an_upstream_outage_reports_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    response = await _post_test(_configured_app(monkeypatch, handler))
    assert response.status_code == 503
    assert response.json()["error"] == "PROVIDER_UNAVAILABLE"


async def test_a_malformed_reply_reports_invalid_response_not_an_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """502, not 503: something answered, so the provider is reachable."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    response = await _post_test(_configured_app(monkeypatch, handler))
    assert response.status_code == 502
    assert response.json()["error"] == "PROVIDER_INVALID_RESPONSE"


async def test_an_unconfigured_provider_is_reported_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMICFLOW_RUNTIME", "memory")
    runtime = create_configured_runtime()
    runtime.provider_config_store.clear_text()
    response = await _post_test(create_app(runtime))
    assert response.status_code == 409
    assert response.json()["error"] == "PROVIDER_NOT_CONFIGURED"
