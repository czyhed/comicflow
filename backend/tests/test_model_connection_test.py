import json

import httpx
import pytest
from comicflow.providers.model_connection_test import check_connection


def connection():
    return {"id": "c", "baseUrl": "https://example.test/v3", "apiKey": "secret-test-key"}


def model():
    return {
        "id": "m",
        "connectionId": "c",
        "model": "my-text",
        "protocol": "doubao-chat",
        "config": {
            "timeoutMs": 120000,
            "request": {
                "path": "/custom",
                "body": {
                    "model": "{{model}}",
                    "messages": "{{messages}}",
                    "max_tokens": 8000,
                    "n": 5,
                    "temperature": 0.3,
                },
            },
        },
    }


async def test_text_check_uses_saved_template_with_one_bounded_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    result = await check_connection(connection(), model(), transport=httpx.MockTransport(handler))
    assert result["status"] == "ok"
    assert result["model"] == "my-text"
    assert len(calls) == 1
    assert str(calls[0].url) == "https://example.test/v3/custom"
    payload = json.loads(calls[0].content)
    assert payload["model"] == "my-text"
    assert payload["max_tokens"] == 1
    assert payload["n"] == 1 and payload["stream"] is False
    assert payload["temperature"] == 0.3
    assert payload["messages"] == [{"role": "user", "content": "ping"}]
    assert calls[0].headers["authorization"] == "Bearer secret-test-key"
    assert "secret-test-key" not in json.dumps(result)


@pytest.mark.parametrize(
    "status,reason",
    [
        (400, "request_rejected"),
        (401, "authentication"),
        (403, "permission_denied"),
        (429, "rate_limited"),
        (503, "service_error"),
    ],
)
async def test_text_refusal_does_not_leak_supplier_body(status, reason):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            status,
            json={"error": {"message": "secret-test-key supplier-private-body"}},
        )
    )
    result = await check_connection(connection(), model(), transport=transport)
    assert result["status"] == "failed"
    assert result["reason"] == reason and result["upstreamStatus"] == status
    assert "supplier-private-body" not in json.dumps(result)
    assert "secret-test-key" not in json.dumps(result)


@pytest.mark.parametrize(
    "body",
    [
        {"error": "no"},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"refusal": "blocked"}}]},
    ],
)
async def test_http_200_is_not_enough_for_text_success(body):
    result = await check_connection(
        connection(),
        model(),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
    )
    assert result["status"] == "failed"


async def test_address_check_is_partial_and_never_sends_key_or_follows_redirect():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET" and "authorization" not in request.headers
        return httpx.Response(302, headers={"Location": "https://other.test"})

    result = await check_connection(connection(), None, transport=httpx.MockTransport(handler))
    assert result["status"] == "partial"
    assert result["scope"] == "address" and result["upstreamStatus"] == 302
    assert len(calls) == 1


async def test_timeout_and_invalid_model_make_no_generation_calls():
    from comicflow.domain.errors import DomainError

    def handler(request):
        raise httpx.ReadTimeout("secret-test-key", request=request)

    result = await check_connection(connection(), model(), transport=httpx.MockTransport(handler))
    assert result["reason"] == "timeout"
    bad = {**model(), "protocol": "compshare-h3"}
    with pytest.raises(DomainError, match="MODEL_CAPABILITY_UNSUPPORTED"):
        await check_connection(connection(), bad, transport=httpx.MockTransport(handler))


async def test_response_mapping_and_safe_parameter_diagnostic():
    selected = model()
    selected["config"]["responseTextPath"] = "output.text"
    result = await check_connection(
        connection(),
        selected,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"output": {"text": "ok"}})
        ),
    )
    assert result["status"] == "ok"
    result = await check_connection(
        connection(),
        selected,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                400,
                json={
                    "error": {
                        "code": "InvalidParameter",
                        "param": "max_tokens",
                        "message": "private",
                    }
                },
            )
        ),
    )
    assert result["reason"] == "invalid_parameter"
    assert result["parameter"] == "max_tokens"


def test_api_checks_revision_and_connection_before_network(monkeypatch):
    from comicflow.api.app import create_app
    from comicflow.infrastructure.memory import create_memory_runtime
    from fastapi.testclient import TestClient

    calls = []

    async def fake_check(conn, selected):
        calls.append((conn, selected))
        return {"status": "ok", "scope": "text", "message": "test", "elapsedMs": 1}

    monkeypatch.setattr("comicflow.api.model_registry.check_connection", fake_check)
    with TestClient(create_app(create_memory_runtime())) as client:
        root = "/api/model-registry"
        data = client.post(
            root + "/connections",
            json={
                "revision": 0,
                "name": "c",
                "baseUrl": "https://example.test",
                "apiKey": "secret",
            },
        ).json()
        cid = data["connections"][0]["id"]
        data = client.post(
            root + "/models",
            json={
                "revision": 1,
                "name": "text",
                "connectionId": cid,
                "model": "my-text",
                "protocol": "doubao-chat",
                "enabled": False,
                "config": {},
            },
        ).json()
        mid = data["models"][0]["id"]
        path = root + f"/connections/{cid}/test"
        assert client.post(path, json={"revision": 1, "modelId": mid}).status_code == 409
        assert calls == []
        response = client.post(path, json={"revision": 2, "modelId": mid})
        assert response.status_code == 200 and response.json()["revision"] == 2
        assert len(calls) == 1 and calls[0][0]["apiKey"] == "secret"
        assert calls[0][1]["id"] == mid
        assert client.get(root).json()["revision"] == 2
