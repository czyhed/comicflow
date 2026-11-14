import json
from pathlib import Path
from shutil import copytree

import httpx
import pytest
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider

SKILL_DIRECTORY = Path(__file__).resolve().parents[2] / "skills/h3-prompt-writing"


async def test_text_adapter_receives_skill_preserves_dialogue_and_does_not_retry():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "# H3 Prompt Writing" in body["messages"][0]["content"]
        assert body["model"] == "offline-text"
        if len(calls) > 1:
            return httpx.Response(500)
        result = {
            "durationSec": 5,
            "sections": {
                "integrated_multimodal_description": (
                    "[Shot 1] A woman waves and says <d>[Chinese] 等一下！</d>"
                ),
                "overall_soundscape": "Rain falls.",
                "non_diegetic_music": "N/A",
            },
        }
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(result, ensure_ascii=False)}}]
        })

    provider = BailianTextProvider(
        api_key="offline", base_url="https://text.test/v1", model="offline-text",
        max_retries=3, transport=httpx.MockTransport(handler),
    )
    writer = H3SkillPromptWriter(provider.compile_h3_prompt)
    shot = {"id": "s1", "durationSec": 5, "dialogue": "等一下！"}
    result = await writer.write(shot, [])
    assert "<d>[Chinese] 等一下！</d>" in result["prompt"]
    assert len(calls) == 1
    with pytest.raises(RuntimeError, match="PROVIDER_HTTP_ERROR"):
        await writer.write(shot, [])
    assert len(calls) == 2


async def test_h3_cannot_bypass_skill_with_saved_prompt():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403)

    provider = MinimaxH3Provider(api_key="offline", transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="H3_PROMPT_WRITER_REQUIRED"):
        await provider.generate({"id": "s1", "h3Prompt": "bypass"}, [])
    assert calls == []


async def test_reference_images_never_use_video_provider():
    pipeline = create_memory_runtime().pipeline
    calls = []

    class Video:
        async def generate(self, shot, characters):
            raise AssertionError("Reference request reached video provider")

    class Image:
        async def generate(self, shot, characters):
            calls.append(shot)
            return {"mediaType": "image", "sourceUrl": "https://assets.test/image.png"}

    class Store:
        async def presigned_get_url(self, *args, **kwargs):
            return "https://assets.test/image.png"

    pipeline._asset_store = Store()
    pipeline._dynamic_visual_provider = Video()
    pipeline._reference_image_provider = Image()
    await pipeline._generate_character_reference(
        {"id": "c1", "name": "小雨", "appearance": "短发", "clothing": "蓝色外套"}, "p1"
    )
    await pipeline._generate_scene_background(
        {"id": "scene1", "location": "车站", "time": "夜晚"}, "p1"
    )
    assert [item["imagePurpose"] for item in calls] == ["character-reference", "scene-background"]
    assert all("p1" in item["id"] for item in calls)


async def valid_rewrite(system, user):
    data = json.loads(user)
    plan = data["referenceManifest"]
    description = "[Shot 1] A woman stands at a quiet bus stop. The camera slowly pushes in."
    labels = " ".join(item["label"] for item in plan["images"])
    if labels:
        description += " Preserve the appearance and environment from " + labels + "."
    sections = {
        "integrated_multimodal_description": description,
        "overall_soundscape": "Rain taps the roof.",
        "non_diegetic_music": "N/A",
    }
    if plan["mode"] == "ref2va":
        sections = {
            "subject_definitions": "<Subject 1> is the woman from " + labels + ".",
            "summary": "[reference generation] <Subject 1> waits at the bus stop.",
            "retention_analysis": (
                "<Subject 1> (appears in [Shot 1]): fully_preserved - appearance."
            ),
            "detailed_description": description + " <Subject 1> remains near the curb.",
            "overall_soundscape": "Rain taps the roof.",
            "non_diegetic_music": "N/A",
        }
    return {"durationSec": plan["durationSec"], "sections": sections}


@pytest.mark.parametrize(
    "mode,extras,characters,count",
    [
        ("t2va", {}, [], 3),
        ("i2va", {"firstFrameUrl": "https://x/first.png"}, [], 3),
        (
            "fl2va",
            {"firstFrameUrl": "https://x/first.png", "lastFrameUrl": "https://x/last.png"},
            [],
            3,
        ),
        ("l2va", {"lastFrameUrl": "https://x/last.png"}, [], 3),
        ("ref2va", {}, [{"id": "c1", "referenceImageUrl": "https://x/c1.png"}], 6),
    ],
)
async def test_skill_runs_before_every_submission(mode, extras, characters, count):
    events = []

    async def complete(system, user):
        assert "# H3 Prompt Writing" in system
        assert "### 4.2 Shots and Cuts" in system
        assert ("Full-Reference Mode Rewrite Output Format Guide" in system) == (count == 6)
        assert "bypass" not in user
        events.append("skill")
        result = await valid_rewrite(system, user)
        assert len(result["sections"]) == count
        return result

    def handler(request):
        if request.method == "POST":
            events.append("submit")
            body = json.loads(request.content)
            assert body["duration"] == 5
            assert "[Shot 1]" in body["content"][0]["text"]
            return httpx.Response(200, json={"task_id": "task"})
        if "/query/" in request.url.path:
            return httpx.Response(
                200, json={"task": {"status": "succeeded", "content": {"url": "https://x/out.mp4"}}}
            )
        return httpx.Response(200, content=b"video")

    provider = MinimaxH3Provider(
        api_key="offline",
        prompt_writer=H3SkillPromptWriter(complete),
        transport=httpx.MockTransport(handler),
    )
    shot = {"id": "s1", "durationSec": 5, "generationMode": mode, "h3Prompt": "bypass", **extras}
    for _ in range(2):
        result = await provider.generate(shot, characters)
        assert result["promptExecution"]["skill"] == "h3-prompt-writing"
        assert len(result["promptExecution"]["sha256"]) == 64
        assert result["generationMode"] == mode
    assert events == ["skill", "submit", "skill", "submit"]
    assert shot["h3Prompt"] == "bypass"


async def test_skill_file_changes_and_missing_files_are_seen_per_call(tmp_path):
    directory = tmp_path / "skill"
    copytree(SKILL_DIRECTORY, directory)
    writer = H3SkillPromptWriter(valid_rewrite, skill_dir=directory)
    first = await writer.write({"id": "s1", "durationSec": 5}, [])
    with (directory / "SKILL.md").open("a", encoding="utf-8") as output:
        output.write("\nChanged instructions.\n")
    second = await writer.write({"id": "s1", "durationSec": 5}, [])
    assert first["execution"]["sha256"] != second["execution"]["sha256"]
    (directory / "SKILL.md").unlink()
    with pytest.raises(RuntimeError, match="H3_SKILL_UNAVAILABLE"):
        await writer.write({"id": "s1"}, [])


@pytest.mark.parametrize("problem", ["format", "duration", "label", "language", "mode"])
async def test_bad_rewrite_or_input_never_reaches_h3(problem):
    requests = []

    async def complete(system, user):
        result = await valid_rewrite(system, user)
        if problem == "format":
            result["sections"].pop("overall_soundscape")
        elif problem == "duration":
            result["durationSec"] = 9
        elif problem == "label":
            result["sections"]["integrated_multimodal_description"] += " <Picture 9>"
        elif problem == "language":
            result["sections"]["integrated_multimodal_description"] += " 中文描述"
        return result

    def handler(request):
        requests.append(request)
        raise AssertionError("Unexpected video request")

    provider = MinimaxH3Provider(
        api_key="offline",
        prompt_writer=H3SkillPromptWriter(complete),
        transport=httpx.MockTransport(handler),
    )
    shot = {"id": "s1", "durationSec": 5}
    if problem == "mode":
        shot.update({"generationMode": "ref2va", "firstFrameUrl": "https://x/frame.png"})
    with pytest.raises(RuntimeError):
        await provider.generate(shot, [])
    assert requests == []


async def test_reference_endpoint_persists_reuses_and_rejects_video_results():
    from comicflow.api.app import create_app

    runtime = create_memory_runtime()
    generated = []

    class Images:
        media_type = "video"

        async def generate(self, shot, characters):
            generated.append(shot["id"])
            return {"mediaType": self.media_type, "sourceUrl": "https://x/image.png"}

    images = Images()
    runtime.pipeline.set_reference_image_provider(images)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/projects",
                json={
                    "inputType": "story",
                    "story": "雨夜车站，小雨正在等车。",
                    "durationSec": 30,
                    "mode": "import_story",
                },
            )
        ).json()
        pid = created["project"]["id"]
        path = "/api/projects/" + pid
        card = (
            await client.post(
                path + "/characters",
                json={
                    "name": "小雨",
                    "appearance": "短发",
                    "clothing": "蓝衣",
                    "personality": "沉稳",
                    "voice": {"language": "zh-CN"},
                },
            )
        ).json()
        version = created["project"]["version"]
        endpoint = path + "/references/characters/" + card["id"]
        rejected = await client.post(endpoint, json={"expectedVersion": version})
        assert rejected.status_code == 400
        assert rejected.json()["error"] == "REFERENCE_IMAGE_INVALID"
        assert "referenceImageUrl" not in (await client.get(path + "/characters")).json()[0]
        images.media_type = "image"
        response = await client.post(endpoint, json={"expectedVersion": version})
        assert response.status_code == 200
        assert response.json()["reused"] is False
        repeat = await client.post(
            endpoint, json={"expectedVersion": response.json()["projectVersion"]}
        )
        assert repeat.json()["reused"] is True
        assert len(generated) == 2
        assert (await client.get(path + "/characters")).json()[0][
            "referenceImageMediaType"
        ] == "image"
