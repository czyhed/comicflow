import json
from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider


@pytest.mark.parametrize("endpoint", ["preview", "split"])
@pytest.mark.parametrize("failure", ["read", "connect", "rejected", "invalid"])
@pytest.mark.parametrize("retries", [0, 2])
async def test_split_error_is_single_request_and_does_not_mutate_project(
    endpoint, failure, retries
):
    calls = []

    def handler(request):
        calls.append(request)
        if failure in {"read", "connect"}:
            cls = httpx.ReadTimeout if failure == "read" else httpx.ConnectTimeout
            raise cls("private-data-must-not-leak", request=request)
        if failure == "rejected":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": "InvalidParameter",
                        "param": "max_tokens",
                        "message": "private",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "无效结果",
                                    "scenes": [],
                                    "shots": [],
                                }
                            )
                        }
                    }
                ]
            },
        )

    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜，两人在车站相遇。",
            mode="automatic",
            duration_sec=30,
        )
    )
    pid = created["project"]["id"]
    record = await runtime.pipeline._repository.get(pid)
    record.project["generatedStoryText"] = "雨夜，两人在车站相遇。"
    record.project["stage"] = "story-generated"
    await runtime.pipeline._repository.save(record)
    before = deepcopy(record.project)
    runtime.pipeline.set_text_provider(
        BailianTextProvider(
            api_key="test-key",
            base_url="https://provider.test/v1",
            timeout_seconds=120,
            max_retries=retries,
            transport=httpx.MockTransport(handler),
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)),
        base_url="http://test",
    ) as client:
        response = await client.post(f"/api/projects/{pid}/script/{endpoint}", json={})
    assert len(calls) == 1
    assert (await runtime.pipeline._repository.get(pid)).project == before
    assert "private" not in response.text
    detail = response.json()
    if failure in {"read", "connect"}:
        assert response.status_code == 504
        assert detail["stage"] == "script_split"
        assert detail["timeoutMs"] == 120000
        assert detail["timeoutPhase"] == failure
    elif failure == "rejected":
        assert response.status_code == 400
        assert detail["stage"] == "script_split"
        assert detail["reason"] == "invalid_parameter"
        assert detail["parameter"] == "max_tokens"
    else:
        assert response.status_code >= 400


async def test_registry_split_uses_saved_budget_and_template_without_retry():
    from comicflow.providers.model_selection import ModelSelection
    from comicflow.providers.text_errors import TextRequestError

    snapshot = {
        "bindings": {"script": "m"},
        "connections": [
            {
                "id": "c",
                "baseUrl": "https://provider.test/v3",
                "apiKey": "test-key",
            }
        ],
        "models": [
            {
                "id": "m",
                "connectionId": "c",
                "model": "chosen-model",
                "enabled": True,
                "protocol": "doubao-chat",
                "config": {
                    "timeoutMs": 300000,
                    "request": {
                        "path": "/chat/completions",
                        "body": {
                            "model": "{{model}}",
                            "messages": "{{messages}}",
                            "temperature": 0.7,
                        },
                    },
                },
            }
        ],
    }
    provider = ModelSelection(snapshot, None).provider("script", None)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.extensions["timeout"]["read"] == 300
        body = json.loads(request.content)
        assert body["model"] == "chosen-model"
        assert "script_split" in body["messages"][0]["content"]
        assert body["temperature"] == 0.7
        raise httpx.ReadTimeout("private", request=request)

    provider._transport.inner = httpx.MockTransport(handler)
    with pytest.raises(TextRequestError) as caught:
        await provider.split_script("故事", "project", 30)
    assert caught.value.detail["stage"] == "script_split"
    assert caught.value.detail["timeoutMs"] == 300000
    assert len(calls) == 1
