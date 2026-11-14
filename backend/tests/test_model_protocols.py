import json

import httpx
import pytest
from comicflow.domain.errors import DomainError
from comicflow.providers.model_protocols import TemplateTransport, render, validate_config


def test_templates_keep_json_value_types_and_all_messages():
    variables = {"messages": [{"role": "system", "content": "Skill rules"}], "stream": False}
    result = render(
        {"input": "{{messages}}", "stream": "{{stream}}", "temperature": 0.5}, variables
    )
    assert result["input"] == variables["messages"]
    assert result["stream"] is False
    assert isinstance(result["temperature"], float)
    with pytest.raises(DomainError):
        render("prefix {{messages}}", variables)


@pytest.mark.parametrize(
    "config",
    [
        {"request": {"path": "https://another-host.test"}},
        {"request": {"path": "//another-host.test"}},
        {"request": {"body": {"messages": "{{missing}}"}}},
        {"request": {"body": {"messages": "remove-all-skills"}}},
        {"request": {"headers": {"Authorization": "Bearer hardcoded-key"}}},
        {"request": {"headers": {"Host": "another-host.test"}}},
        {"responseTextPath": '__import__("os")'},
        {"timeoutMs": True},
    ],
)
def test_malformed_or_unsafe_protocol_settings_are_rejected(config):
    with pytest.raises(DomainError, match="MODEL_CONFIG_INVALID"):
        validate_config("chat-completions", config)


async def test_custom_body_and_response_mapping_use_exact_configured_endpoint():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"result": {"text": "hello"}})

    config = validate_config(
        "chat-completions",
        {
            "request": {
                "path": "/custom",
                "body": {
                    "model": "{{model}}",
                    "messages": "{{messages}}",
                    "temperature": 0.2,
                },
                "headers": {"Authorization": "Bearer {{apiKey}}"},
            },
            "responseTextPath": "result.text",
        },
    )
    transport = TemplateTransport(
        config, "https://example.test/v3", "private-key", httpx.MockTransport(handle)
    )
    async with httpx.AsyncClient(
        base_url="https://example.test/v3",
        transport=transport,
        headers={"Authorization": "Bearer old"},
    ) as client:
        result = await client.post(
            "/chat/completions",
            json={
                "model": "chosen",
                "messages": [{"role": "system", "content": "Skill retained"}],
            },
        )
    assert result.json()["choices"][0]["message"]["content"] == "hello"
    assert str(seen[0].url) == "https://example.test/v3/custom"
    assert seen[0].headers.get_list("Authorization") == ["Bearer private-key"]
    assert json.loads(seen[0].content)["messages"][0]["content"] == "Skill retained"


@pytest.mark.parametrize(
    "config",
    [
        {"resolution": "720P"},
        {"request": {"body": {"referenceImages": []}}},
        {"submitPath": "//other.test/submit"},
        {"queryPath": "/no-task-id"},
    ],
)
def test_h3_templates_cannot_bypass_resolution_references_or_task_contract(config):
    with pytest.raises(DomainError):
        validate_config("compshare-h3", config)
