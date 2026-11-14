"""A script preview must accept shots that omit the line key they do not use.

The model omits ``narration`` on shots that carry dialogue (and vice versa),
which is a valid script. Treating a missing optional key as a malformed
provider response rejected fully compliant scripts with
PROVIDER_INVALID_RESPONSE.
"""

import pytest
from comicflow.production.script_preview import normalize_preview


def _script(shots: list[dict[str, object]]) -> dict[str, object]:
    """A 30-second script: the contract requires 2 scenes and 6 shots."""
    filler = [_shot(f"filler_{index}") for index in range(6 - len(shots))]
    all_shots = [*shots, *filler]
    half = len(all_shots) // 2
    return {
        "title": "雨夜书页",
        "scenes": [
            {
                "id": "scene_1",
                "title": "雨夜异书",
                "time": "夜晚",
                "location": "老书店内",
                "narrativeGoal": "建立神秘氛围",
                "conflict": "理性抗拒超自然现象",
                "turningPoint": "新闻应验",
                "shotIds": [str(shot["id"]) for shot in all_shots[:half]],
            },
            {
                "id": "scene_2",
                "title": "雨中挽手",
                "time": "次日夜",
                "location": "轨道桥下",
                "narrativeGoal": "完成情感高潮",
                "conflict": "时间紧迫",
                "turningPoint": "拉住女儿的手",
                "shotIds": [str(shot["id"]) for shot in all_shots[half:]],
            },
        ],
        "shots": all_shots,
    }


def _shot(shot_id: str, **overrides: object) -> dict[str, object]:
    shot: dict[str, object] = {
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
    shot.update(overrides)
    return shot


def test_preview_accepts_a_dialogue_shot_that_omits_narration() -> None:
    """Observed real qwen output: a spoken shot carries no narration key."""
    dialogue_shot = _shot("shot_1", dialogue="……真的发生了。")
    del dialogue_shot["narration"]
    script = _script([dialogue_shot, _shot("shot_2")])

    result = normalize_preview(script, target_duration_sec=30)

    shot = next(item for item in result["shots"] if item["id"] == "shot_1")
    assert shot["dialogue"] == "……真的发生了。"
    assert shot["narration"] == ""


def test_preview_accepts_a_narration_shot_that_omits_dialogue() -> None:
    """The mirror case must hold too: narration-only shots need no dialogue key."""
    narration_shot = _shot("shot_1", narration="书烧尽了。而她还活着。")
    del narration_shot["dialogue"]
    script = _script([narration_shot, _shot("shot_2")])

    result = normalize_preview(script, target_duration_sec=30)

    shot = next(item for item in result["shots"] if item["id"] == "shot_1")
    assert shot["narration"] == "书烧尽了。而她还活着。"
    assert shot["dialogue"] == ""


def test_preview_accepts_a_shot_with_explicitly_empty_lines() -> None:
    silent = _shot("shot_1", dialogue="", narration="")
    script = _script([silent, _shot("shot_2")])
    result = normalize_preview(script, target_duration_sec=30)
    assert result['shots'][0]['dialogue'] == result['shots'][0]['narration'] == ''


@pytest.mark.parametrize('missing', [('dialogue',), ('narration',), ('dialogue', 'narration')])
def test_preview_still_rejects_unspecified_speech(missing) -> None:
    silent = _shot('shot_1', dialogue='', narration='')
    for field in missing:
        silent.pop(field)
    with pytest.raises(RuntimeError, match="PROVIDER_INVALID_RESPONSE"):
        normalize_preview(_script([silent]), target_duration_sec=30)


def test_preview_still_rejects_non_string_line_values() -> None:
    """A present-but-wrongly-typed line is a genuine contract violation."""
    malformed = _shot("shot_1", dialogue=["你终于来了。"])
    script = _script([malformed, _shot("shot_2")])

    with pytest.raises(RuntimeError, match="PROVIDER_INVALID_RESPONSE"):
        normalize_preview(script, target_duration_sec=30)
