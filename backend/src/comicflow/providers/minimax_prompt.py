"""Build prompts following the bundled MiniMax H3 prompt-writing skill."""

from __future__ import annotations

from comicflow.domain.models import JsonObject


def build_h3_prompt(
    *, shot: JsonObject, scene: JsonObject | None = None, characters: list[JsonObject] | None = None
) -> str:
    """Build the base H3 prompt sections consumed by T2VA/I2VA/FL2VA.

    Reference URLs stay in the API ``content`` array. The prompt only names
    stable labels so the same label can be resolved across all sections.
    """
    mode = str(shot.get("generationMode") or "t2va").lower()
    scene = scene or {}
    characters = characters or []
    labels = [f"<Subject {index}>" for index, _ in enumerate(characters, start=1)]
    subjects = ", ".join(labels) or "the shot subject"
    location = str(scene.get("location") or "unspecified environment")
    moment = str(scene.get("time") or "consistent time and lighting")
    duration = float(shot.get("durationSec") or 5)
    action = str(shot.get("action") or "moves naturally")
    emotion = str(shot.get("emotion") or "calm")
    camera = str(shot.get("cameraMovement") or "holds a stable shot")
    style = str(shot.get("visualStyle") or "consistent comic animation style")
    dialogue = str(shot.get("dialogue") or "").strip()
    sections = [
        f"Target duration: {duration:.0f} seconds. Mode: {mode}.",
        "integrated_multimodal_description:",
        f"At 0.00 seconds, preserve the established composition and introduce {subjects} "
        "in <Scene A>. ",
        f"{style}. The scene is {location}, {moment}. {subjects} {action}, showing {emotion}. ",
        f"The camera {camera}. Describe a continuous visual path for the full "
        f"{duration:.0f} seconds.",
    ]
    if dialogue:
        sections.append(f"The speaking character says: <d>[Chinese] {dialogue}</d>")
    sections.extend(
        [
            "overall_soundscape:",
            str(shot.get("soundscape") or "Natural environmental sound matching the scene."),
            "non_diegetic_music:",
            str(shot.get("music") or "Subtle music with no abrupt style change."),
        ]
    )
    return "\n".join(sections)
