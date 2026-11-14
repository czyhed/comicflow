from __future__ import annotations

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject


def build_dialogue(
    *, shot_id: str, speaker_id: str, text: str, start_ms: int, duration_ms: int
) -> JsonObject:
    if not text.strip():
        raise DomainError("DIALOGUE_INVALID")
    if duration_ms <= 0:
        raise DomainError("AUDIO_DURATION_INVALID")
    return {
        "shotId": shot_id,
        "speakerId": speaker_id,
        "text": text,
        "startMs": start_ms,
        "endMs": start_ms + duration_ms,
    }


def format_chinese_subtitle(dialogue: JsonObject, *, max_chars: int = 16) -> JsonObject:
    text = str(dialogue["text"]).strip()
    lines = [text[index : index + max_chars] for index in range(0, len(text), max_chars)]
    return {
        "text": "\n".join(lines),
        "startMs": dialogue["startMs"],
        "endMs": max(dialogue["endMs"], dialogue["startMs"] + 800),
    }


def build_shot_timeline(
    *, shot: JsonObject, visual_asset: JsonObject, dialogue: JsonObject | None = None
) -> JsonObject:
    dialogue_end = int(dialogue["endMs"]) if dialogue else 0
    duration_ms = max(int(float(shot["durationSec"]) * 1000), dialogue_end)

    def track(value: object) -> list[JsonObject]:
        return [{"type": value, "startMs": 0, "endMs": duration_ms}] if value else []

    return {
        "shotId": shot["id"],
        "durationMs": duration_ms,
        "visualAssetId": visual_asset["id"],
        "actionTrack": track(shot.get("action")),
        "expressionTrack": track(shot.get("emotion")),
        "cameraTrack": track(shot.get("cameraMotion")),
        "dialogue": [dialogue] if dialogue else [],
        "subtitle": [format_chinese_subtitle(dialogue)] if dialogue else [],
        "lipSyncTrack": [],
        "transitionIn": shot.get("transitionIn"),
        "transitionOut": shot.get("transitionOut") or shot.get("transition"),
    }
