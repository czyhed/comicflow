from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping

from comicflow.domain.models import JsonObject

_QUESTION_TYPES = {"goal", "conflict", "turn", "ending", "character", "constraint"}
_BEAT_TYPES = ("setup", "development", "turn", "ending")


class ScriptContractError(RuntimeError):
    """Contract location only: callers must never pass model values as paths."""

    def __init__(
        self, rule: str, path: str, *, actual: int | None = None,
        minimum: int | None = None, maximum: int | None = None,
    ) -> None:
        super().__init__("PROVIDER_INVALID_RESPONSE")
        self.validation: JsonObject = {"rule": rule, "path": path}
        for key, value in (("actual", actual), ("min", minimum), ("max", maximum)):
            if value is not None:
                self.validation[key] = value


def normalize_generation_message(
    body: object,
    *,
    expected_kind: str,
    expected_mode: str,
    expected_task: str,
) -> JsonObject:
    """Validate the routing envelope before a task-specific normalizer runs."""
    envelope = _envelope(
        body,
        expected_kind,
        expected_mode=expected_mode,
        expected_task=expected_task,
        require_routing=True,
    )
    return envelope


def normalize_story_message(body: object, *, target_duration_sec: int) -> JsonObject:
    envelope = _envelope(body, "story_text")
    content = envelope["content"]
    if not isinstance(content, dict):
        raise _invalid()
    title = content.get("title")
    logline = content.get("logline")
    setting = content.get("setting")
    text = content.get("text")
    characters = content.get("characters")
    beats = content.get("beats")
    if (
        not _non_empty_text(title, 2, 80)
        or not _non_empty_text(logline, 10, 240)
        or not _non_empty_text(setting, 10, 300)
        or not _non_empty_text(text, _story_min_chars(target_duration_sec), 8000)
        or not isinstance(characters, list)
        or not characters
        or not isinstance(beats, list)
        or len(beats) != len(_BEAT_TYPES)
    ):
        raise _invalid()
    normalized_characters: list[JsonObject] = []
    for character in characters:
        if not isinstance(character, dict) or not _non_empty_text(character.get("name"), 1, 80):
            raise _invalid()
        normalized_characters.append(
            {
                "name": str(character["name"]).strip(),
                "goal": str(character.get("goal", "")).strip(),
            }
        )
    normalized_beats: list[JsonObject] = []
    for expected_type, beat in zip(_BEAT_TYPES, beats, strict=True):
        if (
            not isinstance(beat, dict)
            or beat.get("type") != expected_type
            or not _non_empty_text(beat.get("text"), 20, 1200)
        ):
            raise _invalid()
        normalized_beats.append({"type": expected_type, "text": str(beat["text"]).strip()})
    return {
        "title": str(title).strip(),
        "logline": str(logline).strip(),
        "characters": normalized_characters,
        "setting": str(setting).strip(),
        "beats": normalized_beats,
        "text": str(text).strip(),
    }


def valid_speech_fields(shot: JsonObject) -> bool:
    """Accept spoken text or explicitly empty speech, never an omitted decision."""
    lines = [shot.get(field, '') for field in ('dialogue', 'narration')]
    return all(isinstance(line, str) for line in lines) and (
        any(line.strip() for line in lines)
        or all(field in shot for field in ('dialogue', 'narration'))
    )


def normalize_script_message(
    body: object, *, target_duration_sec: int, character_map: dict[str, str] | None = None
) -> JsonObject:
    envelope = _envelope(body, "script")
    content = envelope["content"]
    if not isinstance(content, dict):
        raise _invalid()
    title = content.get("title")
    scenes = content.get("scenes")
    shots = content.get("shots")
    if not _non_empty_text(title, 2, 80):
        raise ScriptContractError("title_length", "title", minimum=2, maximum=80)
    if not isinstance(scenes, list):
        raise ScriptContractError("array_required", "scenes")
    if not isinstance(shots, list):
        raise ScriptContractError("array_required", "shots")
    scene_count, shot_min, shot_max = _script_scale(target_duration_sec)
    if len(scenes) != scene_count:
        raise ScriptContractError("scene_count", "scenes", actual=len(scenes),
                                  minimum=scene_count, maximum=scene_count)
    if not shot_min <= len(shots) <= shot_max:
        raise ScriptContractError("shot_count", "shots", actual=len(shots),
                                  minimum=shot_min, maximum=shot_max)
    shot_ids: set[str] = set()
    shot_scene_ids: dict[str, str] = {}
    normalized_shots: list[JsonObject] = []
    for order, shot in enumerate(shots, start=1):
        path = f"shots[{order - 1}]"
        if not isinstance(shot, dict):
            raise ScriptContractError("object_required", path)
        required = (
            "id",
            "title",
            "action",
            "emotion",
            "shotSize",
            "durationSec",
            "visualDescription",
        )
        for field in required:
            if field != "durationSec" and (
                not isinstance(shot.get(field), str) or not str(shot[field]).strip()
            ):
                raise ScriptContractError("required_text", f"{path}.{field}")
        duration = shot.get("durationSec")
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or duration <= 0):
            raise ScriptContractError("positive_duration", f"{path}.durationSec")
        for field in ("dialogue", "narration"):
            if not isinstance(shot.get(field, ""), str):
                raise ScriptContractError("text_type", f"{path}.{field}")
        if not valid_speech_fields(shot):
            raise ScriptContractError("speech_required", path)
        shot_id = str(shot["id"])
        if shot_id in shot_ids:
            raise ScriptContractError("duplicate_id", f"{path}.id")
        shot_ids.add(shot_id)
        if "sceneId" in shot:
            if not isinstance(shot.get("sceneId"), str):
                raise ScriptContractError("text_type", f"{path}.sceneId")
            shot_scene_ids[shot_id] = str(shot["sceneId"])
        normalized_shot = dict(shot)
        normalized_shot["order"] = order
        for field, default in (
            ("cameraMovement", "固定镜头"),
            ("visualStyle", "统一漫画风格，色彩和线条保持连续"),
            ("soundscape", "安静的环境声"),
            ("music", "克制的背景音乐，无突兀变化"),
            ("generationMode", "t2va"),
        ):
            value = normalized_shot.get(field, default)
            if not isinstance(value, str) or not value.strip():
                raise ScriptContractError("required_text", f"{path}.{field}")
            normalized_shot[field] = (
                value.strip().lower() if field == "generationMode" else value.strip()
            )
        if normalized_shot["generationMode"] not in {"t2va", "i2va", "fl2va", "l2va", "ref2va"}:
            raise ScriptContractError("generation_mode", f"{path}.generationMode")

        # Process characters field: map character names to IDs if character_map is provided
        character_names = shot.get("characters")
        if character_names is not None:
            if not isinstance(character_names, list):
                raise ScriptContractError("string_list", f"{path}.characters")
            if not all(isinstance(name, str) for name in character_names):
                raise ScriptContractError("string_list", f"{path}.characters")
            # Map names to IDs; skip names not found in character_map (warning, not error)
            if character_map is not None:
                character_ids = []
                for name in character_names:
                    name_stripped = str(name).strip()
                    if name_stripped and name_stripped in character_map:
                        character_ids.append(character_map[name_stripped])
                normalized_shot["characterIds"] = character_ids
            else:
                normalized_shot["characterIds"] = shot.get("characterIds", [])
        else:
            # LLM didn't provide characters field, default to empty
            normalized_shot["characterIds"] = shot.get("characterIds", [])

        ids = normalized_shot["characterIds"]
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
            raise ScriptContractError("string_list", f"{path}.characterIds")
        normalized_shot["characterIds"] = list(dict.fromkeys(ids))

        normalized_shots.append(normalized_shot)
    total_duration = sum(float(shot["durationSec"]) for shot in normalized_shots)
    if not 30 <= total_duration <= 90:
        raise ScriptContractError("total_duration", "shots", minimum=30, maximum=90)
    referenced: list[str] = []
    normalized_scenes: list[JsonObject] = []
    scene_ids: set[str] = set()
    for index, scene in enumerate(scenes):
        path = f"scenes[{index}]"
        if not isinstance(scene, dict):
            raise ScriptContractError("object_required", path)
        for field, maximum in (("id", 100), ("title", 120)):
            if not _non_empty_text(scene.get(field), 1, maximum):
                raise ScriptContractError("required_text", f"{path}.{field}")
        if scene["id"] in scene_ids:
            raise ScriptContractError("duplicate_id", f"{path}.id")
        scene_ids.add(scene["id"])
        shot_ids_for_scene = scene.get("shotIds")
        if not isinstance(shot_ids_for_scene, list) or not shot_ids_for_scene:
            raise ScriptContractError("nonempty_list", f"{path}.shotIds")
        if any(not isinstance(item, str) for item in shot_ids_for_scene):
            raise ScriptContractError("string_list", f"{path}.shotIds")
        referenced.extend(shot_ids_for_scene)
        for shot_id in shot_ids_for_scene:
            if shot_id in shot_scene_ids and shot_scene_ids[shot_id] != str(scene["id"]):
                shot_index = next(i for i, shot in enumerate(shots) if shot["id"] == shot_id)
                raise ScriptContractError("scene_reference", f"shots[{shot_index}].sceneId")
        normalized_scenes.append(dict(scene))
    if set(referenced) != shot_ids or len(referenced) != len(shot_ids):
        raise ScriptContractError("shot_references", "scenes")
    return {"title": str(title).strip(), "scenes": normalized_scenes, "shots": normalized_shots}


def validate_script_content(script: object, *, target_duration_sec: int) -> list[JsonObject]:
    try:
        normalize_script_message(
            {"kind": "script", "version": 1, "content": script},
            target_duration_sec=target_duration_sec,
        )
    except RuntimeError:
        return [{"code": "SCRIPT_CONTENT_INVALID"}]
    return []


def normalize_guided_question_message(body: object) -> JsonObject:
    envelope = _envelope(body, "guided_question")
    content = envelope["content"]
    if not isinstance(content, dict):
        raise _invalid()
    question_id = content.get("questionId")
    question_type = content.get("questionType")
    question = content.get("question")
    missing_fields = content.get("missingFields")
    options = content.get("options", [])
    done = content.get("done")
    if (
        not _non_empty_text(question_id, 1, 80)
        or not isinstance(question_type, str)
        or question_type not in _QUESTION_TYPES
        or not isinstance(question, str)
        or len(question) > 80
        or not isinstance(missing_fields, list)
        or not all(isinstance(item, str) and item for item in missing_fields)
        or not isinstance(options, list)
        or len(options) > 3
        or not all(isinstance(item, str) and item for item in options)
        or not isinstance(done, bool)
        or (done and question.strip())
        or (not done and not question.strip())
    ):
        raise _invalid()
    return {
        "questionId": str(question_id).strip(),
        "questionType": question_type,
        "question": question.strip(),
        "missingFields": [item.strip() for item in missing_fields],
        "options": [item.strip() for item in options],
        "done": done,
    }


def _envelope(
    body: object,
    expected_kind: str,
    *,
    expected_mode: str | None = None,
    expected_task: str | None = None,
    require_routing: bool = False,
) -> JsonObject:
    if isinstance(body, str):
        cleaned = re.sub(r"<think>.*?</think>", "", body, flags=re.DOTALL).strip()
        if "```" in cleaned or cleaned != body.strip():
            raise _invalid()
        try:
            body = json.loads(cleaned)
        except json.JSONDecodeError as error:
            raise _invalid() from error
    if not isinstance(body, Mapping):
        raise _invalid()
    if body.get("kind") != expected_kind or body.get("version") != 1:
        raise _invalid()
    mode = body.get("mode")
    task = body.get("task")
    if require_routing and (
        not isinstance(mode, str)
        or not isinstance(task, str)
        or mode != expected_mode
        or task != expected_task
    ):
        raise RuntimeError("GENERATION_MODE_MISMATCH")
    content = body.get("content")
    if not isinstance(content, Mapping):
        raise _invalid()
    result: JsonObject = {"kind": expected_kind, "version": 1, "content": dict(content)}
    if isinstance(mode, str):
        result["mode"] = mode
    if isinstance(task, str):
        result["task"] = task
    return result


def _non_empty_text(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, str) and minimum <= len(value.strip()) <= maximum


def _story_min_chars(target_duration_sec: int) -> int:
    if target_duration_sec <= 30:
        return 300
    if target_duration_sec <= 60:
        return 600
    return 900


def _script_scale(target_duration_sec: int) -> tuple[int, int, int]:
    if target_duration_sec <= 30:
        return 2, 6, 6
    if target_duration_sec <= 60:
        return 3, 8, 10
    return 4, 10, 12


def _invalid() -> RuntimeError:
    return RuntimeError("PROVIDER_INVALID_RESPONSE")
