"""H3 receives approved character views only in reference mode."""

import io
import json

import httpx
from comicflow.providers.h3_inputs import prepare_images
from comicflow.providers.h3_skill import H3SkillPromptWriter, reference_plan
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from PIL import Image


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (256, 256), "navy").save(output, format="PNG")
    return output.getvalue()


def _character() -> dict:
    return {
        "id": "c1",
        "name": "Student",
        "appearance": "short black hair",
        "clothing": "blue jacket",
        "referenceImageUrl": "https://assets.test/main.png",
        "referenceViews": [
            {"id": "v-front", "view": "front", "viewLabel": "front",
             "url": "https://assets.test/front.png"},
            {"id": "v-three-quarter", "view": "three-quarter", "viewLabel": "three-quarter",
             "url": "https://assets.test/three-quarter.png"},
            {"id": "v-profile", "view": "profile", "viewLabel": "profile",
             "url": "https://assets.test/profile.png"},
        ],
    }


def test_reference_plan_includes_main_image_and_all_approved_views_in_stable_order():
    plan = reference_plan({"id": "s1", "durationSec": 5}, [_character()])

    assert plan["mode"] == "ref2va"
    assert [item["url"] for item in plan["images"]] == [
        "https://assets.test/main.png",
        "https://assets.test/front.png",
        "https://assets.test/three-quarter.png",
        "https://assets.test/profile.png",
    ]
    assert [item["label"] for item in plan["images"]] == [
        "<Picture 1>", "<Picture 2>", "<Picture 3>", "<Picture 4>",
    ]


async def test_prepare_images_reads_view_object_keys_before_text_or_video():
    events = []

    class Store:
        async def get_bytes(self, key, max_bytes):
            events.append(key)
            return _png()

    character = _character()
    character["referenceImageUrl"] = "http://127.0.0.1:19000/main.png"
    character["referenceImageObjectKey"] = "main.png"
    for view in character["referenceViews"]:
        view["url"] = "http://127.0.0.1:19000/" + view["view"] + ".png"
        view["objectKey"] = view["view"] + ".png"

    _shot, prepared = await prepare_images({"id": "s1"}, [character], Store())

    assert events == ["main.png", "front.png", "three-quarter.png", "profile.png"]
    assert prepared[0]["referenceImageUrl"].startswith("data:image/png;base64,")
    assert all(view["url"].startswith("data:image/png;base64,")
               for view in prepared[0]["referenceViews"])


async def test_h3_submission_contains_all_character_views():
    calls = []

    async def complete(system, user):
        data = json.loads(user)
        labels = " ".join(item["label"] for item in data["referenceManifest"]["images"])
        return {
            "durationSec": 5,
            "sections": {
                "subject_definitions": "<Subject 1> is the character from " + labels + ".",
                "summary": "[reference generation] The character stands still.",
                "retention_analysis": (
                    "<Subject 1> (appears in [Shot 1]): fully_preserved - identity."
                ),
                "detailed_description": (
                    "[Shot 1] The character stands still, preserving " + labels + "."
                ),
                "overall_soundscape": "Quiet room tone.",
                "non_diegetic_music": "N/A",
            },
        }

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"task_id": "task-views"})
        if "/query/" in request.url.path:
            return httpx.Response(200, json={"task": {
                "status": "succeeded", "content": {"url": "https://assets.test/video.mp4"},
            }})
        return httpx.Response(200, content=b"video")

    provider = MinimaxH3Provider(
        api_key="offline",
        prompt_writer=H3SkillPromptWriter(complete),
        transport=httpx.MockTransport(handler),
    )
    result = await provider.generate(
        {"id": "s1", "durationSec": 5}, [_character()]
    )

    body = json.loads(calls[0].content)
    assert [item["role"] for item in body["content"][1:]] == [
        "reference_image", "reference_image", "reference_image", "reference_image",
    ]
    assert len(body["content"]) == 5
    assert result["generationMode"] == "ref2va"
