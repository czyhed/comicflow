from comicflow.production.pipeline import ProductionPipeline


def test_script_contract_rejects_orphan_shots_and_short_scene_content() -> None:
    errors = ProductionPipeline._validate_script(
        {
            "title": "雨夜回头",
            "scenes": [
                {
                    "id": "scene-1",
                    "title": "车站",
                    "time": "午夜",
                    "location": "站台",
                    "narrativeGoal": "",
                    "conflict": "姐姐不肯相认",
                    "turningPoint": "车门即将关闭",
                    "shotIds": ["shot-1"],
                }
            ],
            "shots": [
                {
                    "id": "shot-1",
                    "sceneId": "scene-1",
                    "action": "回头",
                    "emotion": "惊讶",
                    "shotSize": "特写",
                    "durationSec": 30,
                    "visualDescription": "姐姐在车窗后回头",
                    "dialogue": "你终于来了。",
                    "narration": "",
                },
                {
                    "id": "orphan",
                    "sceneId": "scene-2",
                    "action": "离开",
                    "emotion": "悲伤",
                    "shotSize": "远景",
                    "durationSec": 30,
                    "visualDescription": "林默站在雨中",
                    "dialogue": "",
                    "narration": "列车驶远。",
                },
            ],
        }
    )
    codes = {str(error["code"]) for error in errors}
    assert "SCENE_SHOT_REFERENCE_INVALID" in codes
    assert "SCENE_FIELDS_REQUIRED" in codes

