"""A script preview must accept scenes with missing or empty context fields.

Scene context fields (time, location, narrativeGoal, conflict, turningPoint) are
optional metadata for the screenwriter. The downstream pipeline (visual generation,
audio generation, composition) does not use them. They should be validated for type
correctness if present, but empty or missing values are acceptable.

This is the same class of defect as #2 (dialogue/narration): validating by presence
rather than by semantic need. The fix follows the same pattern.
"""

import pytest
from comicflow.production.script_preview import normalize_preview


def _script(scenes: list[dict[str, object]] | None = None) -> dict[str, object]:
    """A 30-second script: the contract requires 2 scenes and 6 shots."""
    if scenes is None:
        scenes = [
            {
                "id": "scene_1",
                "title": "雨夜异书",
                "time": "夜晚",
                "location": "老书店内",
                "narrativeGoal": "建立神秘氛围",
                "conflict": "理性抗拒超自然现象",
                "turningPoint": "新闻应验",
                "shotIds": ["shot_1", "shot_2", "shot_3"],
            },
            {
                "id": "scene_2",
                "title": "雨中挽手",
                "time": "次日夜",
                "location": "轨道桥下",
                "narrativeGoal": "完成情感高潮",
                "conflict": "时间紧迫",
                "turningPoint": "拉住女儿的手",
                "shotIds": ["shot_4", "shot_5", "shot_6"],
            },
        ]
    shots = [_shot(f"shot_{i}") for i in range(1, 7)]
    return {"title": "雨夜书页", "scenes": scenes, "shots": shots}


def _shot(shot_id: str) -> dict[str, object]:
    return {
        "id": shot_id,
        "title": "泛黄书脊",
        "action": "镜头推入店内",
        "emotion": "警觉",
        "shotSize": "medium close-up",
        "durationSec": 5,
        "visualDescription": "暖黄台灯晕染旧书脊",
        "dialogue": "",
        "narration": "雨声渐密。",
    }


def test_preview_accepts_scene_with_all_context_fields() -> None:
    """Baseline: a fully populated scene passes validation."""
    script = _script()

    result = normalize_preview(script, target_duration_sec=30)

    assert len(result["scenes"]) == 2
    assert result["scenes"][0]["time"] == "夜晚"
    assert result["scenes"][0]["location"] == "老书店内"


def test_preview_accepts_scene_missing_all_context_fields() -> None:
    """Scene context fields are optional metadata, not pipeline requirements."""
    minimal_scenes = [
        {
            "id": "scene_1",
            "title": "雨夜异书",
            "shotIds": ["shot_1", "shot_2", "shot_3"],
        },
        {
            "id": "scene_2",
            "title": "雨中挽手",
            "shotIds": ["shot_4", "shot_5", "shot_6"],
        },
    ]
    script = _script(scenes=minimal_scenes)

    result = normalize_preview(script, target_duration_sec=30)

    assert len(result["scenes"]) == 2
    assert result["scenes"][0]["title"] == "雨夜异书"


def test_preview_accepts_scene_with_empty_context_fields() -> None:
    """Empty strings in context fields are acceptable (model may provide them)."""
    sparse_scenes = [
        {
            "id": "scene_1",
            "title": "雨夜异书",
            "time": "",
            "location": "老书店内",
            "narrativeGoal": "",
            "conflict": "",
            "turningPoint": "",
            "shotIds": ["shot_1", "shot_2", "shot_3"],
        },
        {
            "id": "scene_2",
            "title": "雨中挽手",
            "time": "次日夜",
            "location": "",
            "narrativeGoal": "完成情感高潮",
            "conflict": "",
            "turningPoint": "",
            "shotIds": ["shot_4", "shot_5", "shot_6"],
        },
    ]
    script = _script(scenes=sparse_scenes)

    result = normalize_preview(script, target_duration_sec=30)

    assert len(result["scenes"]) == 2
    assert result["scenes"][0]["location"] == "老书店内"
    assert result["scenes"][1]["time"] == "次日夜"


def test_preview_accepts_scene_with_partial_context_fields() -> None:
    """A scene may provide some context fields but not others."""
    partial_scenes = [
        {
            "id": "scene_1",
            "title": "雨夜异书",
            "time": "夜晚",
            "location": "老书店内",
            "shotIds": ["shot_1", "shot_2", "shot_3"],
            # omit narrativeGoal, conflict, turningPoint
        },
        {
            "id": "scene_2",
            "title": "雨中挽手",
            "narrativeGoal": "完成情感高潮",
            "conflict": "时间紧迫",
            "shotIds": ["shot_4", "shot_5", "shot_6"],
            # omit time, location, turningPoint
        },
    ]
    script = _script(scenes=partial_scenes)

    result = normalize_preview(script, target_duration_sec=30)

    assert len(result["scenes"]) == 2
    assert result["scenes"][0]["time"] == "夜晚"
    assert result["scenes"][1]["narrativeGoal"] == "完成情感高潮"


def test_preview_rejects_non_string_context_field() -> None:
    """If a context field is present, it must be a string (type safety)."""
    malformed_scenes = [
        {
            "id": "scene_1",
            "title": "雨夜异书",
            "time": ["夜晚"],  # wrong type
            "location": "老书店内",
            "shotIds": ["shot_1", "shot_2", "shot_3"],
        },
        {
            "id": "scene_2",
            "title": "雨中挽手",
            "shotIds": ["shot_4", "shot_5", "shot_6"],
        },
    ]
    script = _script(scenes=malformed_scenes)

    with pytest.raises(RuntimeError, match="PROVIDER_INVALID_RESPONSE"):
        normalize_preview(script, target_duration_sec=30)


def test_preview_rejects_integer_context_field() -> None:
    """Context fields must be strings, not other types like integers."""
    malformed_scenes = [
        {
            "id": "scene_1",
            "title": "雨夜异书",
            "narrativeGoal": 42,  # wrong type
            "shotIds": ["shot_1", "shot_2", "shot_3"],
        },
        {
            "id": "scene_2",
            "title": "雨中挽手",
            "shotIds": ["shot_4", "shot_5", "shot_6"],
        },
    ]
    script = _script(scenes=malformed_scenes)

    with pytest.raises(RuntimeError, match="PROVIDER_INVALID_RESPONSE"):
        normalize_preview(script, target_duration_sec=30)
