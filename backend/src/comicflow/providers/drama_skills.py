"""Load and compile project adapters for the two non-H3 drama skills."""

from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import cast

from comicflow.domain.models import JsonObject
from comicflow.production.visual_styles import StyleStage, style_instructions

MANJU_SKILL = "manju-laoli-drama"
XIAOLUO_SKILL = "xiaoluo-visual-assets"
_SKILLS_ROOT = Path(__file__).resolve().parents[4] / "skills"
_SKILL_FILES = {
    MANJU_SKILL: "manju-laoli-drama/SKILL.md",
    XIAOLUO_SKILL: "xiaoluo-visual-assets/SKILL.md",
}
_REFERENCES = {
    (XIAOLUO_SKILL, "character-text-board"): (
        "xiaoluo-visual-assets/references/character-text-board.md"),
    (XIAOLUO_SKILL, "character-board"): "xiaoluo-visual-assets/references/character-board.md",
    (MANJU_SKILL, "story"): "manju-laoli-drama/references/story-planning.md",
    (MANJU_SKILL, "script"): "manju-laoli-drama/references/script-planning.md",
    (MANJU_SKILL, "continuity"): "manju-laoli-drama/references/continuity-and-quality.md",
    (MANJU_SKILL, "quality"): "manju-laoli-drama/references/continuity-and-quality.md",
    (XIAOLUO_SKILL, "character-prompt"): (
        "xiaoluo-visual-assets/references/character-prompt-writing.md"),
    (XIAOLUO_SKILL, "character-reference"): "xiaoluo-visual-assets/references/character-assets.md",
    (XIAOLUO_SKILL, "character-view"): "xiaoluo-visual-assets/references/character-assets.md",
    (XIAOLUO_SKILL, "scene-background"): "xiaoluo-visual-assets/references/scene-assets.md",
}


def load_stage_skill(skill: str, task: str) -> JsonObject:
    """Read the stage file and only the reference needed by this task."""
    main = _SKILL_FILES.get(skill)
    reference = _REFERENCES.get((skill, task))
    if main is None or reference is None:
        raise RuntimeError("DRAMA_SKILL_UNKNOWN")
    try:
        files = [main, reference]
        contents = [(_SKILLS_ROOT / file).read_text(encoding="utf-8") for file in files]
    except (OSError, UnicodeError) as error:
        raise RuntimeError("DRAMA_SKILL_UNAVAILABLE") from error
    if any(not content.strip() for content in contents):
        raise RuntimeError("DRAMA_SKILL_UNAVAILABLE")
    combined = "\n\n".join(contents)
    return {
        "prompt": combined
        + f"\n\nComicFlow task: {task}. Keep the existing ComicFlow JSON contract. "
        "Return only fields required by the caller.",
        "execution": {
            "skill": skill,
            "task": task,
            "files": files,
            "sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        },
    }


def review_shot_speech(shot: JsonObject) -> JsonObject:
    """Estimate authored speech budget without rewriting any script text."""
    dialogue = str(shot.get("dialogue") or "")
    narration = str(shot.get("narration") or "")
    dialogue_chars = len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", dialogue))
    narration_chars = len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", narration))
    total_chars = dialogue_chars + narration_chars
    duration = float(shot.get("durationSec") or 0)
    estimated = total_chars / 5 if total_chars else 0
    severity = "p0" if estimated > duration > 0 else "p1" if total_chars > 24 else "ok"
    return {
        "spokenCharacterCount": dialogue_chars,
        "narrationCharacterCount": narration_chars,
        "totalCharacterCount": total_chars,
        "estimatedSpeechSec": round(estimated, 2),
        "durationSec": duration,
        "severity": severity,
    }


def prepare_visual_asset_request(shot: JsonObject) -> JsonObject:
    """Apply XiaoLuo rules to one character or scene image request."""
    purpose = str(shot.get("imagePurpose", ""))
    task = {
        "character-reference": "character-reference",
        "character-reference-view": "character-view",
        "character-reference-board": "character-board",
        "character-reference-text-board": "character-text-board",
        "scene-background": "scene-background",
    }.get(purpose)
    if task is None:
        raise RuntimeError("DRAMA_SKILL_TASK_INVALID")
    material = load_stage_skill(XIAOLUO_SKILL, task)
    request = deepcopy(shot)
    base = str(request.get("visualDescription", "")).strip()
    if not base:
        raise RuntimeError("REFERENCE_IMAGE_PROMPT_REQUIRED")
    if purpose in {"character-reference-board", "character-reference-text-board"}:
        # Compile only this stage's reference, not the front-only main-image instructions.
        rules = (_SKILLS_ROOT / _REFERENCES[(XIAOLUO_SKILL, task)]).read_text(encoding="utf-8")
        request['visualDescription'] = base + '\n\n' + rules
        request['skillExecution'] = material['execution']
        if request.get('styleSnapshot') is not None:
            request['visualDescription'] += '\n' + style_instructions(
                request['styleSnapshot'], cast(StyleStage, purpose))
            request['styleApplication'] = {'engine': 'local-style-v1', 'stage': purpose,
                'presetId': request['styleSnapshot']['presetId'],
                'revision': request['styleSnapshot']['revision']}
        return request
    if request.get('styleSnapshot') is not None:
        stage = {
            'character-reference': 'character-reference',
            'character-reference-view': 'character-reference-view',
            'scene-background': 'scene-background',
        }[purpose]
        # Keep stage identity/space rules, using the selected medium instead of
        # inferring realism from keywords in user-authored appearance text.
        constraints = style_instructions(request['styleSnapshot'], cast(StyleStage, stage))
        view = str(request.get('view', ''))
        if view:
            constraints += f'本次观察角度：{view}。'
        request['visualDescription'] = f'{base}\n\n{constraints}\n竖版 9:16 构图。'
        request['skillExecution'] = material['execution']
        request['styleApplication'] = {'engine': 'local-style-v1', 'stage': stage,
                                      'presetId': request['styleSnapshot']['presetId'],
                                      'revision': request['styleSnapshot']['revision']}
        return request
    view = str(request.get("view", "")).strip()
    visual_style = f"{base} {request.get('visualStyle', '')}".lower()
    stylized = any(token in visual_style for token in (
        "\u6f2b\u753b", "\u52a8\u6f2b", "\u63d2\u753b", "\u6c34\u58a8",
        "\u4e8c\u6b21\u5143", "\u56fd\u6f2b",
        "anime", "illustration",
    ))
    material_detail = (
        "线条粗细稳定，色块边缘干净，笔触和上色层次服从原稿指定媒介，"
        "仅表现已有服饰和配饰的材质，不叠加摄影皮肤纹理"
        if stylized else
        "按原稿指定媒介表现皮肤、发束与已有服饰的层次，材质响应与光源一致；"
        "三维使用体积和受控高光，写实保留自然肤质，不因未选预设强制改为真人照片"
    )
    if purpose == "character-reference":
        constraints = (
            "\n\u3010\u89d2\u8272\u89c6\u89c9\u9501\uff5c\u89d2\u8272\u8eab\u4efd\u951a\u70b9\uff5c\u6700\u9ad8\u4f18\u5148\u7ea7\u3011\u4fdd\u6301\u63d0\u793a\u8bcd\u4e2d\u5b9a\u4e49\u7684\u5e74\u9f84\u611f\u3001\u8138\u578b\u9aa8\u76f8\u3001\u7709\u773c\u9f3b\u5507\u3001"
            "\u53d1\u578b\u53d1\u8272\u3001\u80a4\u8272\u3001\u4f53\u578b\u6bd4\u4f8b\u548c\u6807\u5fd7\u6027\u7279\u5f81\uff1b\u8fd9\u4e9b\u5185\u5bb9\u4e0d\u5f97\u88ab\u753b\u98ce\u3001\u5149\u7ebf\u3001\u59ff\u52bf\u6216\u80cc\u666f\u6539\u53d8\u3002"
            "\n\u3010\u5f53\u524d\u9020\u578b\u3011\u4e25\u683c\u4fdd\u6301\u670d\u88c5\u5c42\u7ea7\u3001\u526a\u88c1\u3001\u989c\u8272\u3001\u914d\u9970\u3001\u78e8\u635f\u548c\u5b63\u8282\u903b\u8f91\uff1b\u4e0d\u8981\u628a\u8eab\u4efd\u7279\u5f81\u4e0e\u670d\u88c5\u72b6\u6001\u6df7\u6dc6\uff0c\u4e0d\u5f97\u64c5\u81ea\u589e\u52a0\u5e3d\u5b50\u3001\u6b66\u5668\u3001\u9996\u9970\u6216\u5176\u4ed6\u670d\u88c5\u3002"
            f"\n\u3010\u6750\u8d28\u7ec6\u8282\u3011{material_detail}\u3002"
            "\n\u3010\u6444\u5f71\u4e0e\u6784\u56fe\u3011\u9ad8\u7aef\u89d2\u8272\u8bbe\u5b9a\u56fe\uff0c\u5355\u4e00\u4eba\u7269\u3001\u5168\u8eab\u3001\u6b63\u9762\u3001\u81ea\u7136\u7ad9\u59ff\uff0c\u8138\u90e8\u548c\u670d\u88c5\u65e0\u906e\u6321\uff1b"
            "50mm \u7b49\u6548\u89c6\u89d2\uff0c\u4eba\u7269\u6bd4\u4f8b\u81ea\u7136\uff0c"
            "\u773c\u775b\u548c\u670d\u88c5\u7ec6\u8282\u6e05\u6670\u5bf9\u7126\uff0c"
            "\u4e3b\u4f53\u5360\u753b\u9762\u7ea6 70%\uff0c"
            "\u56db\u5468\u7559\u51fa\u5b89\u5168\u8fb9\u754c\u3002"
            "\n\u3010\u5e03\u5149\u4e0e\u540e\u671f\u3011\u4e3b\u5149\u65b9\u5411\u4e3a\u5de6\u524d\u65b9\uff0c\u67d4\u548c\u5927\u9762\u79ef\u4e3b\u5149\u3001\u5f31\u8865\u5149\u3001\u7ec6\u5fae\u8f6e\u5ed3\u5149\uff0c\u53d7\u63a7\u9634\u5f71\uff0c"
            "\u5e72\u51c0\u8272\u5f69\u5206\u79bb\uff0c\u660e\u6697\u8fc7\u6e21\u7ec6\u817b\uff0c\u4fdd\u6301\u7edf\u4e00\u753b\u98ce\uff1b\u7981\u6b62\u5851\u6599\u611f\u3001\u68da\u62cd\u8fc7\u66dd\u3001\u810f\u566a\u70b9\u548c\u8fc7\u5ea6\u9510\u5316\u3002"
            "\n\u3010\u80cc\u666f\u4e0e\u7981\u6b62\u9879\u3011\u4e2d\u6027\u4f4e\u5e72\u6270\u7eaf\u8272\u80cc\u666f\uff0c\u4eba\u7269\u8f6e\u5ed3\u6e05\u695a\uff1b\u4e0d\u5f97\u65b0\u589e\u4eba\u7269\u3001\u6587\u5b57\u3001\u6807\u7b7e\u3001\u8fb9\u6846\u6216\u6c34\u5370\u3002"
        )
    elif purpose == "character-reference-view":
        constraints = (
            "\n\u3010\u89d2\u8272\u89c6\u89c9\u9501\uff5c\u8eab\u4efd\u4e0d\u53ef\u53d8\u3011"
            "\u751f\u6210 "
            f"{view or 'front'} \u89c6\u89d2\uff0c\u53ea\u6539\u53d8\u89c2\u5bdf\u89d2\u5ea6\uff1b"
            "\u4fdd\u6301\u540c\u4e00\u5f20\u8138\u7684\u8138\u578b\u9aa8\u76f8\u3001\u7709\u773c\u9f3b\u5507\u3001"
            "\u53d1\u578b\u53d1\u8272\u3001\u5e74\u9f84\u611f\u3001\u4f53\u578b\u6bd4\u4f8b\u548c\u6807\u5fd7\u6027\u7279\u5f81\u3002"
            "\n\u3010\u5f53\u524d\u9020\u578b\u9501\u3011\u4fdd\u6301\u540c\u4e00\u5957\u670d\u88c5\u7684\u5c42\u7ea7\u3001\u526a\u88c1\u3001\u989c\u8272\u3001\u914d\u9970\u3001\u78e8\u635f\u548c\u6750\u8d28\u7ec6\u8282\uff1b\u53ea\u6539\u53d8\u673a\u4f4d\uff0c"
            "\u4e0d\u5f97\u91cd\u8bbe\u8ba1\u89d2\u8272\uff0c\u4e0d\u5f97\u65b0\u589e\u4eba\u7269\u3001\u6587\u5b57\u3001\u6807\u7b7e\u3001\u8fb9\u6846\u6216\u6c34\u5370\u3002"
            f"\n\u3010\u6750\u8d28\u7ec6\u8282\u3011{material_detail}\u3002"
            "\n\u3010\u6444\u5f71\u4e0e\u5e03\u5149\u3011\u89c6\u89d2\u53d8\u5316\u6765\u81ea\u771f\u5b9e\u673a\u4f4d\uff0c"
            "50mm \u7b49\u6548\u89c6\u89d2\uff0c\u4eba\u7269\u6bd4\u4f8b\u81ea\u7136\uff0c"
            "\u773c\u775b\u548c\u670d\u88c5\u7ec6\u8282\u6e05\u6670\uff1b"
            "\u4e3b\u5149\u65b9\u5411\u4e3a\u5de6\u524d\u65b9\uff0c\u67d4\u548c\u4e3b\u5149\u3001\u5f31\u8865\u5149\u548c\u7ec6\u5fae\u8f6e\u5ed3\u5149\uff0c\u8272\u5f69\u51c6\u786e\uff0c\u53d7\u63a7\u9634\u5f71\uff0c\u7edf\u4e00\u753b\u98ce\u3002"
        )
    else:
        constraints = (
            "\n【场景空间锚点】保持地点、时间、天气、主光源方向、主要建筑和固定物件位置，"
            "前景、中景、后景和空间纵深清楚；保留角色活动区域与可行走路径。"
            "\n【构图与清晰度】无人场景参考全景，门窗、通路和叙事所需道具保持可辨，"
            "透视自然；景深服务空间定位，不用虚化或遮挡隐藏关键布局。"
            "\n【光影与材质】沿用原稿指定画风和已有光源，材质以已有物件为准，"
            "线条、色块、笔触或体积反光服从对应媒介，不统一套用写实或平涂。"
            "\n【空气透视与氛围】按原定天气和空间保留远近层次；原稿未指定的雨水、"
            "雾、烟尘、霓虹和生活道具不自动加入，干燥或晴朗场景保持原状。"
            "\n【限制】保留已指定空间和配色，无新增人物、动物、对白、文字或水印。"
        )
    request["visualDescription"] = f"{base}\n\n{constraints}\n\n竖版 9:16 构图。"
    request["skillExecution"] = material["execution"]
    return request


def apply_continuity_plan(script: JsonObject) -> JsonObject:
    """Add deterministic continuity metadata while preserving Script fields."""
    planned = deepcopy(script)
    shots = planned.get("shots")
    scenes = planned.get("scenes")
    if not isinstance(shots, list) or not isinstance(scenes, list):
        raise RuntimeError("SCRIPT_CONTINUITY_INPUT_INVALID")
    scene_by_shot = {
        str(shot_id): str(scene.get("id"))
        for scene in scenes
        if isinstance(scene, dict) and isinstance(scene.get("shotIds"), list)
        for shot_id in scene["shotIds"]
    }
    previous_by_scene: dict[str, str] = {}
    valid_shots = [shot for shot in shots if isinstance(shot, dict)]
    for index, shot in enumerate(valid_shots):
        shot_id = str(shot.get("id", ""))
        scene_id = str(shot.get("sceneId") or scene_by_shot.get(shot_id, ""))
        previous = previous_by_scene.get(scene_id)
        speech_review = review_shot_speech(shot)
        action = str(shot.get("action") or "").strip()
        visual = str(shot.get("visualDescription") or "").strip()
        action_before = str(shot.get("actionBefore") or "").strip() or (
            f"动作开始前：保持“{visual}”中的起始位置和姿态，尚未开始“{action}”。"
        )
        action_middle = str(shot.get("actionMiddle") or "").strip() or (
            f"动作进行中：连续展示“{action}”的关键物理过程，不跳切、不瞬移。"
        )
        action_after = str(shot.get("actionAfter") or "").strip() or (
            f"动作完成后：必须完整完成“{action}”并稳定停在结果位置，"
            "不得停在准备、首次接触或中间状态。"
        )
        shot["continuityPlan"] = {
            "sceneId": scene_id,
            "previousShotId": previous,
            "continuityRule": (
                "continue_from_previous_shot_tail" if previous else "establish_scene_anchor"
            ),
            "actionBefore": action_before,
            "actionMiddle": action_middle,
            "actionAfter": action_after,
            "dialogueReview": {
                **speech_review,
            },
            "beat": (
                "setup" if index == 0 else
                "ending" if index == len(valid_shots) - 1 else
                "turn" if index in {max(1, len(valid_shots) // 2)} else "development"
            ),
        }
        if scene_id and shot_id:
            previous_by_scene[scene_id] = shot_id
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        members = [shot for shot in valid_shots if str(shot.get("id")) in scene.get("shotIds", [])]
        scene["continuityPlan"] = {
            "shotCount": len(members),
            "anchor": {
                "location": scene.get("location", ""),
                "time": scene.get("time", ""),
                "lighting": scene.get("lighting", ""),
            },
            "axisRule": "keep_camera_on_one_side_of_the_180_degree_action_axis",
        }
    planned["planningExecution"] = load_stage_skill(MANJU_SKILL, "continuity")["execution"]
    return planned
