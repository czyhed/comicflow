import json

import httpx
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.drama_skills import (
    MANJU_SKILL,
    XIAOLUO_SKILL,
    apply_continuity_plan,
    load_stage_skill,
    prepare_visual_asset_request,
)


def test_stage_skill_loader_routes_only_the_required_references() -> None:
    story = load_stage_skill(MANJU_SKILL, "story")
    character = load_stage_skill(XIAOLUO_SKILL, "character-reference")
    scene = load_stage_skill(XIAOLUO_SKILL, "scene-background")

    assert "主角目标" in story["prompt"]
    assert "角色锁" in character["prompt"]
    assert "默认无人" in scene["prompt"]
    assert story["execution"]["skill"] == MANJU_SKILL
    assert len(story["execution"]["sha256"]) == 64
    assert "references/scene-assets.md" not in character["execution"]["files"]


def test_text_provider_loads_planning_and_character_skills() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        calls.append(system)
        if len(calls) == 2:
            content = {
                "appearance": "二十多岁，黑色短发，面部轮廓清晰",
                "clothing": "蓝色棉布外套，银色拉链",
                "personality": "沉稳敏锐",
                "referenceImagePrompt": "年轻女子，黑色短发，蓝色棉布外套，全身正面，白色背景",
            }
        else:
            content = {"title": "雨夜", "scenes": [], "shots": []}
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]}
        )

    provider = BailianTextProvider(
        api_key="offline", base_url="https://text.test/v1",
        transport=httpx.MockTransport(handler), max_retries=0,
    )

    async def run() -> None:
        await provider.generate_script("雨夜车站的故事", "p1")
        await provider.generate_character_prompt({"fields": {"name": "小雨"}})

    import asyncio

    asyncio.run(run())
    assert "主角目标" in calls[0]
    assert "角色锁" in calls[1]


def test_visual_asset_request_keeps_user_prompt_and_records_skill() -> None:
    request = prepare_visual_asset_request({
        "id": "c1",
        "imagePurpose": "character-reference-view",
        "view": "profile",
        "visualDescription": "用户自己的水墨角色提示词",
    })

    assert request["visualDescription"].startswith("用户自己的水墨角色提示词")
    assert "profile" in request["visualDescription"]
    assert "同一张脸" in request["visualDescription"]
    assert request["skillExecution"]["skill"] == XIAOLUO_SKILL


def test_continuity_plan_links_shots_within_each_scene() -> None:
    planned = apply_continuity_plan({
        "title": "雨夜",
        "scenes": [{"id": "scene-1", "title": "车站", "shotIds": ["s1", "s2"]}],
        "shots": [
            {"id": "s1", "action": "等待", "durationSec": 5, "dialogue": "你来了。"},
            {"id": "s2", "action": "回头", "durationSec": 5, "dialogue": "别回头。"},
        ],
    })

    assert planned["planningExecution"]["skill"] == MANJU_SKILL
    assert planned["shots"][0]["continuityPlan"]["continuityRule"] == "establish_scene_anchor"
    assert planned["shots"][1]["continuityPlan"]["previousShotId"] == "s1"
    assert planned["shots"][1]["continuityPlan"]["dialogueReview"]["severity"] == "ok"


def test_continuity_plan_supplies_visible_action_states_for_legacy_shots() -> None:
    planned = apply_continuity_plan({
        "title": "深夜便利店",
        "scenes": [{"id": "scene-1", "title": "店门", "shotIds": ["s1"]}],
        "shots": [{
            "id": "s1",
            "action": "推开玻璃门并进入便利店",
            "visualDescription": "角色站在便利店门外",
            "durationSec": 5,
            "dialogue": "有人吗？",
        }],
    })

    continuity = planned["shots"][0]["continuityPlan"]
    assert continuity["actionBefore"]
    assert continuity["actionMiddle"]
    assert continuity["actionAfter"]
    assert "不得停在" in continuity["actionAfter"]


def test_continuity_plan_counts_dialogue_and_narration_in_one_speech_budget() -> None:
    planned = apply_continuity_plan({
        "title": "暴雨末班车",
        "scenes": [{"id": "scene-1", "title": "车站", "shotIds": ["s1"]}],
        "shots": [{
            "id": "s1", "action": "冲上末班车", "durationSec": 5,
            "dialogue": "", "narration": ("暴雨把整座城市压成一团模糊的光晕。"
                                      "林夏冲上末班车，车门夹断雨声，车厢空得像一口铁箱。"),
        }],
    })

    review = planned["shots"][0]["continuityPlan"]["dialogueReview"]
    assert review["spokenCharacterCount"] == 0
    assert review["narrationCharacterCount"] > 0
    assert review["totalCharacterCount"] == review["narrationCharacterCount"]
    assert review["estimatedSpeechSec"] > 5
    assert review["severity"] == "p0"


async def test_pipeline_sends_visual_skill_to_every_reference_image() -> None:
    runtime = create_memory_runtime()
    calls: list[dict[str, object]] = []

    class Images:
        async def generate(self, shot, characters):
            del characters
            calls.append(shot)
            return {"mediaType": "image", "sourceUrl": "https://assets.test/result.png"}

    runtime.pipeline.set_reference_image_provider(Images())
    created = await runtime.pipeline.create_project(CreateProject(
        input_type="story", story="雨夜里，小雨在车站等待最后一班车。",
        duration_sec=30, mode="import_story",
    ))
    await runtime.pipeline._generate_character_reference(
        {"id": "c1", "name": "小雨", "appearance": "黑色短发", "clothing": "蓝色外套"},
        created["project"]["id"],
    )
    await runtime.pipeline._generate_scene_background(
        {"id": "scene-1", "location": "车站", "time": "夜晚"},
        created["project"]["id"],
    )

    assert len(calls) == 2
    assert all(call["skillExecution"]["skill"] == XIAOLUO_SKILL for call in calls)
    assert "角色视觉锁" in calls[0]["visualDescription"]
    assert "场景空间锚点" in calls[1]["visualDescription"]
