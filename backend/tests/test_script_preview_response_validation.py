"""Exercise real text adapters through the preview API without billable requests."""

import json
from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.doubao_text import DoubaoTextProvider
from comicflow.providers.model_selection import ModelSelection


def script():
    shots = [
        {
            "id": f"s{i}",
            "title": "走进车站",
            "action": "向前走",
            "emotion": "平静",
            "shotSize": "中景",
            "durationSec": 7.5,
            "visualDescription": "女孩沿着雨中的站台向前走。",
            "dialogue": "我回来了。",
            "narration": "",
            "characters": ["女孩"],
        }
        for i in range(1, 9)
    ]
    scenes = [
        {"id": f"scene{i}", "title": "雨夜车站", "shotIds": ids}
        for i, ids in enumerate((["s1", "s2", "s3"], ["s4", "s5", "s6"], ["s7", "s8"]), 1)
    ]
    return {
        "kind": "script",
        "version": 1,
        "mode": "automatic",
        "task": "script_split",
        "content": {"title": "雨夜归途", "scenes": scenes, "shots": shots},
    }


async def preview(body, *, template=False, inspect_request=None):
    calls = []

    def handler(request):
        calls.append(request)
        if inspect_request is not None:
            inspect_request(request)
        return httpx.Response(200, json=body)

    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="女孩冒雨走过车站，准备乘末班车回家。",
            mode="automatic",
            duration_sec=60,
        )
    )
    pid = created["project"]["id"]
    record = await runtime.pipeline._repository.get(pid)
    record.project.update(generatedStoryText="女孩冒雨回家。", stage="story-generated")
    await runtime.pipeline._repository.save(record)
    before = deepcopy(record.project)
    provider = DoubaoTextProvider(
        api_key="secret-never-print",
        max_retries=2,
        transport=httpx.MockTransport(handler),
    )
    if template:
        provider = ModelSelection(
            {
                "bindings": {"script": "m"},
                "connections": [
                    {
                        "id": "c",
                        "baseUrl": "https://provider.test/v3",
                        "apiKey": "secret-never-print",
                    }
                ],
                "models": [
                    {
                        "id": "m",
                        "connectionId": "c",
                        "enabled": True,
                        "model": "configured-model",
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
                            "responseTextPath": "choices[0].message.content",
                        },
                    }
                ],
            },
            None,
        ).provider("script", None)
        provider._transport.inner = httpx.MockTransport(handler)
    runtime.pipeline.set_text_provider(provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://local"
    ) as client:
        response = await client.post(f"/api/projects/{pid}/script/preview")
    assert len(calls) == 1
    assert (await runtime.pipeline._repository.get(pid)).project == before
    assert "secret-never-print" not in response.text
    return response


@pytest.mark.parametrize("context", ["missing", "", None])
@pytest.mark.parametrize("template", [False, True])
async def test_preview_accepts_optional_scene_context_through_real_adapter(context, template):
    result = script()
    if context != "missing":
        for scene in result["content"]["scenes"]:
            for field in ("time", "location", "narrativeGoal", "conflict", "turningPoint"):
                scene[field] = context
    response = await preview(
        {"choices": [{"message": {"content": json.dumps(result)}}]}, template=template
    )
    assert response.status_code == 200, response.text
    assert response.json()["summary"]["shots"] == 8


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ({"choices": []}, "message_missing"),
        (
            {"choices": [{"finish_reason": "length", "message": {"content": '{"title":'}}]},
            "output_truncated",
        ),
        (
            {"choices": [{"message": {"content": None, "reasoning_content": "private"}}]},
            "reasoning_only",
        ),
        ({"choices": [{"message": {"content": ""}}]}, "empty_content"),
        ({"choices": [{"message": {"content": "private invalid JSON"}}]}, "invalid_json"),
        (
            {"choices": [{"finish_reason": "content_filter", "message": {"content": ""}}]},
            "content_refused",
        ),
    ],
)
@pytest.mark.parametrize("template", [False, True])
async def test_preview_reports_safe_parse_reason_without_retry(body, reason, template):
    response = await preview(body, template=template)
    assert response.status_code == 502
    assert response.json() == {
        "error": "PROVIDER_INVALID_RESPONSE",
        "stage": "script_split",
        "reason": reason,
    }
    assert "private" not in response.text


@pytest.mark.parametrize("defect", ["field_type", "routing", "shot_reference", "shot_count"])
async def test_preview_still_rejects_malformed_script(defect):
    result = script()
    if defect == "field_type":
        result["content"]["scenes"][0]["time"] = 42
    elif defect == "routing":
        result["task"] = "story_expansion"
    elif defect == "shot_reference":
        result["content"]["scenes"][0]["shotIds"] = ["missing"]
    else:
        result["content"]["shots"].pop()
    response = await preview({"choices": [{"message": {"content": json.dumps(result)}}]})
    assert response.status_code == 502
    assert response.json()["reason"] == "script_contract_invalid"


@pytest.mark.parametrize("template", [False, True])
async def test_split_request_has_one_consistent_routing_envelope(template):
    def check(request):
        prompt = json.loads(request.content)["messages"][0]["content"]
        assert '"mode":"automatic","task":"script_split"' in prompt
        assert '"mode":"guided"' not in prompt
        assert '"task":"script_outline"' not in prompt

    response = await preview(
        {"choices": [{"message": {"content": json.dumps(script())}}]},
        template=template,
        inspect_request=check,
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("defect", "rule", "path"),
    [
        ("shot_count", "shot_count", "shots"),
        ("scene_count", "scene_count", "scenes"),
        ("required_field", "required_text", "shots[0].action"),
        ("duration", "positive_duration", "shots[0].durationSec"),
        ("total_duration", "total_duration", "shots"),
        ("line_missing", "speech_required", "shots[0]"),
        ("line_type", "text_type", "shots[0].dialogue"),
        ("shot_duplicate", "duplicate_id", "shots[1].id"),
        ("scene_duplicate", "duplicate_id", "scenes[1].id"),
        ("shot_reference", "shot_references", "scenes"),
        ("scene_reference", "scene_reference", "shots[0].sceneId"),
        ("characters", "string_list", "shots[0].characters"),
        ("music", "required_text", "shots[0].music"),
        ("context", "text_type", "scenes[0].location"),
        ("routing", "routing", "envelope"),
    ],
)
async def test_contract_failure_identifies_safe_field_without_retaining_content(defect, rule, path):
    result = script()
    content = result["content"]
    shots, scenes = content["shots"], content["scenes"]
    if defect == "shot_count":
        shots.pop()
    elif defect == "scene_count":
        scenes.pop()
    elif defect == "required_field":
        shots[0].pop("action")
    elif defect == "duration":
        shots[0]["durationSec"] = "7.5秒"
    elif defect == "total_duration":
        for shot in shots:
            shot["durationSec"] = 20
    elif defect == "line_missing":
        shots[0]["dialogue"] = ""
        shots[0].pop("narration")
    elif defect == "line_type":
        shots[0]["dialogue"] = {"private": "private-model-content"}
    elif defect == "shot_duplicate":
        shots[1]["id"] = shots[0]["id"]
    elif defect == "scene_duplicate":
        scenes[1]["id"] = scenes[0]["id"]
    elif defect == "shot_reference":
        scenes[0]["shotIds"] = ["private-unknown-shot-id"]
    elif defect == "scene_reference":
        shots[0]["sceneId"] = "private-unknown-scene-id"
    elif defect == "characters":
        shots[0]["characters"] = [{"name": "private-model-content"}]
    elif defect == "music":
        shots[0]["music"] = ""
    elif defect == "context":
        scenes[0]["location"] = ["private-model-content"]
    elif defect == "routing":
        result["task"] = "private-wrong-task"
    response = await preview({"choices": [{"message": {"content": json.dumps(result)}}]},
                             template=True)
    assert response.status_code == 502
    assert response.json()["reason"] == "script_contract_invalid"
    validation = response.json()["validation"]
    assert validation["rule"] == rule
    assert validation["path"] == path
    if defect == "shot_count":
        assert validation == {"rule": rule, "path": path, "actual": 7, "min": 8, "max": 10}
    assert "private" not in response.text
