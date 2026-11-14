import pytest
from comicflow.providers.message_contract import (
    normalize_guided_question_message,
    normalize_script_message,
    normalize_story_message,
)


def test_normalize_story_message_requires_versioned_envelope() -> None:
    result = normalize_story_message(
        {
            "kind": "story_text",
            "version": 1,
            "content": {
                "title": "雨夜回头",
                "logline": "失踪十年的姐姐在末班车重新出现",
                "characters": [{"name": "林默", "goal": "找回姐姐"}],
                "setting": "暴雨夜驶向终点的末班车",
                "beats": [
                    {
                        "type": "setup",
                        "text": "林默在暴雨中的末班车等待失踪的姐姐，车站广播反复提醒即将封站。",
                    },
                    {
                        "type": "development",
                        "text": "车厢里的旧线索逐渐指向十年前的真相，乘客们却对那场事故保持沉默。",
                    },
                    {
                        "type": "turn",
                        "text": "姐姐终于承认自己一直在躲避当年的事故，并交出一张被撕碎的旧车票。",
                    },
                    {
                        "type": "ending",
                        "text": "林默决定跟随列车驶向终点寻找答案，即使那里可能没有人等他回来。",
                    },
                ],
                "text": (
                    "这是足够长的故事文本，包含人物目标、环境压力、冲突升级、关键转折和结尾选择。"
                    * 20
                ),
            },
        },
        target_duration_sec=60,
    )
    assert result["title"] == "雨夜回头"
    assert len(result["beats"]) == 4


def test_normalize_messages_rejects_markdown_and_unknown_kind() -> None:
    with pytest.raises(RuntimeError, match="PROVIDER_INVALID_RESPONSE"):
        normalize_script_message('```json {"kind":"script"} ```', target_duration_sec=60)
    with pytest.raises(RuntimeError, match="PROVIDER_INVALID_RESPONSE"):
        normalize_guided_question_message({"kind": "unknown", "version": 1, "content": {}})


def test_normalize_script_message_assigns_missing_shot_order() -> None:
    result = normalize_script_message(
        {
            "kind": "script",
            "version": 1,
            "content": {
                "title": "雨夜",
                "scenes": [
                    {"id": "scene-1", "title": "车站", "shotIds": ["shot-1", "shot-2", "shot-3"]},
                    {"id": "scene-2", "title": "车厢", "shotIds": ["shot-4", "shot-5", "shot-6"]},
                ],
                "shots": [
                    {
                        "id": f"shot-{index}",
                        "title": "回头",
                        "action": "回头",
                        "emotion": "惊讶",
                        "shotSize": "特写",
                        "durationSec": 5,
                        "visualDescription": "姐姐回头",
                        "dialogue": "",
                        "narration": "雨声",
                    }
                    for index in range(1, 7)
                ],
            },
        },
        target_duration_sec=30,
    )

    assert result["shots"][0]["order"] == 1
