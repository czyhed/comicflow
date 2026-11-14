"""The text-provider connectivity probe answers only "can we reach the provider".

It must not apply a content contract. Routing the probe through
``generate_script`` made a reachable provider report as unreachable: the model
replied with a minimal-but-legal JSON object, the full script contract rejected
it, and the resulting code fell through to PROVIDER_UNAVAILABLE.
"""

import httpx
import pytest
from comicflow.providers.bailian_text import BailianTextProvider


def _provider(handler, **kwargs) -> BailianTextProvider:
    return BailianTextProvider(
        api_key="secret-key",
        base_url="https://provider.test/v1",
        transport=httpx.MockTransport(handler),
        max_retries=0,
        **kwargs,
    )


async def test_probe_succeeds_on_a_reply_that_carries_no_script_content() -> None:
    """A reachable provider passes even when the reply has no usable content.

    This is the exact shape that used to fail: an empty title and empty arrays
    satisfy no script contract, but they prove the endpoint and key work.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-key"
        return httpx.Response(
            200,
            json={
                "model": "qwen-plus",
                "choices": [{"message": {"content": '{"title":"","scenes":[],"shots":[]}'}}],
            },
        )

    assert await _provider(handler).check_connectivity() == "qwen-plus"


async def test_probe_requests_a_single_token_and_no_json_contract() -> None:
    """The probe stays cheap: one token, and no response_format constraint."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"model": "qwen-plus", "choices": [{"message": {}}]})

    await _provider(handler).check_connectivity()
    assert seen["max_tokens"] == 1
    assert "response_format" not in seen


async def test_probe_reports_the_model_that_actually_replied() -> None:
    """A provider silently serving a different model is worth surfacing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "qwen-turbo", "choices": [{"message": {}}]})

    assert await _provider(handler, model="qwen-plus").check_connectivity() == "qwen-turbo"


async def test_probe_falls_back_to_the_configured_model_when_none_is_echoed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {}}]})

    assert await _provider(handler, model="qwen-plus").check_connectivity() == "qwen-plus"


@pytest.mark.parametrize("status", [401, 403])
async def test_probe_distinguishes_a_rejected_credential(status: int) -> None:
    """A bad key is a different problem from an unreachable provider."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "invalid api key"}})

    with pytest.raises(RuntimeError, match="PROVIDER_AUTH_FAILED"):
        await _provider(handler).check_connectivity()


async def test_probe_reports_a_server_failure_as_an_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream exploded")

    with pytest.raises(RuntimeError, match="PROVIDER_HTTP_ERROR"):
        await _provider(handler).check_connectivity()


async def test_probe_reports_a_timeout_as_a_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("too slow")

    with pytest.raises(RuntimeError, match="PROVIDER_TIMEOUT"):
        await _provider(handler).check_connectivity()


async def test_probe_rejects_a_reply_that_is_not_a_completion() -> None:
    """Something answered, but it was not the API we expect."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
        await _provider(handler).check_connectivity()
