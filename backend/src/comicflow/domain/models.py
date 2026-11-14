from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

JsonObject = dict[str, Any]


@dataclass(slots=True)
class ProjectRecord:
    project: JsonObject
    guest_session: JsonObject
    jobs: list[JsonObject] = field(default_factory=list)

    def snapshot(self) -> JsonObject:
        project = deepcopy(self.project)
        return {
            "project": project,
            "guestSession": deepcopy(self.guest_session),
            "jobs": deepcopy(self.jobs),
            "creditLedger": deepcopy(project.get("creditLedger", [])),
            "script": deepcopy(project.get("script")),
            "exportManifest": deepcopy(project.get("exportManifest")),
            "visualAssets": deepcopy(project.get("visualAssets", [])),
            "audioAssets": deepcopy(project.get("audioAssets", [])),
            "lipSyncAssets": deepcopy(project.get("lipSyncAssets", [])),
            "timelines": deepcopy(project.get("timelines", {})),
        }


@dataclass(frozen=True, slots=True)
class CreateProject:
    input_type: Literal["idea", "story"]
    story: str
    duration_sec: int
    mode: Literal["guided", "automatic", "import_story", "import_script"]
    style_preset_id: str | None = None


@dataclass(frozen=True, slots=True)
class Actor:
    type: Literal["user", "guest"]
    id: str

    @classmethod
    def user(cls, user_id: str) -> Actor:
        return cls(type="user", id=user_id)

    @classmethod
    def guest(cls, session_id: str) -> Actor:
        return cls(type="guest", id=session_id)
