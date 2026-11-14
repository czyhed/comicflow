from __future__ import annotations

import json

from comicflow.providers.drama_skills import prepare_visual_asset_request
from comicflow.providers.h3_skill import H3SkillPromptWriter


def test_character_image_prompt_has_a_quality_and_identity_scaffold() -> None:
    request = prepare_visual_asset_request({
        "imagePurpose": "character-reference",
        "visualDescription": "二十多岁，短黑发，深蓝外套，冷静克制",
    })
    prompt = request["visualDescription"]
    assert "\\n" not in prompt
    assert prompt.count("\n") >= 5
    for phrase in (
        "身份锚点",
        "当前造型",
        "脸型骨相、眉眼鼻唇",
        "材质细节",
        "摄影与构图",
        "主光方向",
        "轮廓光",
        "单一人物、全身、正面",
        "主体占画面约 70%",
        "背景与禁止项",
    ):
        assert phrase in prompt


def test_stylized_character_prompt_uses_style_specific_material_language() -> None:
    request = prepare_visual_asset_request({
        "imagePurpose": "character-reference",
        "visualStyle": "高级国漫插画",
        "visualDescription": "年轻剑客，黑发，深色长袍",
    })
    prompt = request["visualDescription"]
    assert "线条粗细稳定" in prompt
    assert "真实织物纤维" not in prompt


def test_character_prompt_system_scopes_output_without_copying_costume_examples() -> None:
    from comicflow.providers.character_prompt import character_prompt_system

    system = character_prompt_system({'purpose': 'reference-image'})
    assert '本次JSON字段恰好为：referenceImagePrompt' in system
    assert '不要只堆叠高级' in system
    assert '未选择的字段是约束' in system
    assert '银色绣花针' not in system


def test_scene_image_prompt_has_depth_and_spatial_lighting_scaffold() -> None:
    request = prepare_visual_asset_request({
        "imagePurpose": "scene-background",
        "visualDescription": "雨夜的旧车站月台，冷色霓虹",
    })
    prompt = request["visualDescription"]
    for phrase in (
        "场景空间锚点",
        "前景、中景、后景",
        "主光源方向",
        "空气透视",
        "角色活动区域",
        "无人场景",
    ):
        assert phrase in prompt


async def test_h3_quality_contract_and_final_lock_are_explicit() -> None:
    captured: dict[str, str] = {}

    async def complete(system: str, user: str):
        captured["system"] = system
        captured["user"] = user
        return {
            "durationSec": 5,
            "sections": {
                "integrated_multimodal_description": (
                    "[Shot 1] Character 1 stands beside the window and turns toward the door."
                ),
                "overall_soundscape": "Rain taps the glass.",
                "non_diegetic_music": "N/A",
            },
        }

    result = await H3SkillPromptWriter(complete).write({
        "id": "s1",
        "durationSec": 5,
        "action": "回头看向门口",
        "actionBefore": "保持靠窗站立",
        "actionAfter": "视线停在门口",
        "cameraMovement": "缓慢向前推进",
        "generationMode": "t2va",
    }, [{
        "id": "c1",
        "name": "小雨",
        "appearance": "短黑发，窄脸，左眉尾有小痣",
        "clothing": "深蓝防水外套，银色拉链",
    }])

    for phrase in (
        "identity lock",
        "current look",
        "one primary action",
        "opening state",
        "ending state",
        "screen direction",
        "actionafter",
        "partial progress",
    ):
        assert phrase in captured["system"].lower()
    for phrase in (
        "premium rendering quality",
        "temporal staging",
    ):
        assert phrase in result["prompt"].lower()
    assert "Identity lock" in result["prompt"]
    assert "one primary action" in result["prompt"].lower()
    assert "both feet" in result["prompt"].lower()
    assert "鈥" not in result["prompt"]
    assert "referenceManifest" in json.loads(captured["user"])


def test_script_prompt_requires_visible_action_start_middle_and_end() -> None:
    from comicflow.providers.bailian_text import SCRIPT_SYSTEM_PROMPT

    for field in ("actionBefore", "actionMiddle", "actionAfter"):
        assert field in SCRIPT_SYSTEM_PROMPT
    assert "双脚和身体已完全进入店内" in SCRIPT_SYSTEM_PROMPT


async def test_h3_rejects_translated_picture_labels() -> None:
    async def complete(system: str, user: str):
        del system, user
        return {
            "durationSec": 5,
            "sections": {
                "integrated_multimodal_description": (
                    "[Shot 1] Character 1 begins from @图片1 and holds still."
                ),
                "overall_soundscape": "Rain.",
                "non_diegetic_music": "N/A",
            },
        }

    import pytest

    with pytest.raises(RuntimeError, match="^H3_PROMPT_INVALID$") as error:
        await H3SkillPromptWriter(complete).write({
            "durationSec": 5,
            "generationMode": "i2va",
            "firstFrameUrl": "https://assets.test/first.png",
        }, [])
    assert error.value.reason == "references"
