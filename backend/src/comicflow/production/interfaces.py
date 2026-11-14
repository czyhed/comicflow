from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from comicflow.domain.models import JsonObject, ProjectRecord


class ProjectRepository(Protocol):
    async def get(self, project_id: str) -> ProjectRecord | None: ...

    async def list_projects(self) -> list[ProjectRecord]: ...

    async def save(
        self, record: ProjectRecord, *, outbox_event: JsonObject | None = None
    ) -> None: ...

    async def find_by_job(self, job_id: str) -> ProjectRecord | None: ...

    async def claim_job(self, job_id: str) -> ProjectRecord | None: ...


class TextProvider(Protocol):
    async def generate_story_text(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> str: ...

    async def split_script(
        self, story_text: str, project_id: str, target_duration_sec: int = 60
    ) -> JsonObject: ...

    async def generate_script(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> JsonObject: ...

    async def generate_guided_question(
        self,
        story: str,
        script: JsonObject,
        transcript: list[JsonObject],
        project_id: str,
        target_duration_sec: int = 60,
    ) -> JsonObject: ...

    async def generate_detailed_script(
        self,
        story: str,
        script: JsonObject,
        transcript: list[JsonObject],
        project_id: str,
        target_duration_sec: int = 60,
    ) -> JsonObject: ...

    def stream_story_text(
        self, story: str, project_id: str, target_duration_sec: int = 60
    ) -> AsyncIterator[str]: ...


class ModerationProvider(Protocol):
    async def moderate(self, text: str) -> JsonObject: ...


class CharacterRepository(Protocol):
    async def get(self, character_id: str) -> JsonObject | None: ...

    async def list(self) -> list[JsonObject]: ...

    async def save(self, character: JsonObject, *, expected: JsonObject | None = None) -> None: ...

    async def delete(self, character_id: str) -> bool: ...


class DynamicVisualProvider(Protocol):
    async def generate(
        self, shot: JsonObject, character_inputs: list[JsonObject]
    ) -> JsonObject: ...


class PreviewableVisualProvider(DynamicVisualProvider, Protocol):
    """Video adapters accepted by the shared preflight guard."""

    def prepare_preview(
        self, shot: JsonObject, character_inputs: list[JsonObject],
    ) -> JsonObject: ...


class TtsProvider(Protocol):
    async def generate(self, shot_id: str, speaker_id: str, text: str) -> JsonObject: ...


class LipSyncProvider(Protocol):
    async def generate(
        self, shot_id: str, audio_asset: JsonObject, dialogue: JsonObject
    ) -> JsonObject: ...


class CompositionProvider(Protocol):
    async def compose(self, project: JsonObject) -> JsonObject: ...


class AssetStore(Protocol):
    async def exists(self, object_key: str) -> bool: ...

    async def presigned_download_url(
        self, object_key: str, filename: str, expires_in: int = 900,
    ) -> str: ...

    async def put_bytes(self, object_key: str, content: bytes, content_type: str) -> str: ...

    async def get_bytes(self, object_key: str, max_bytes: int = 20 * 1024 * 1024) -> bytes: ...

    async def presigned_get_url(self, object_key: str, expires_in: int = 900) -> str: ...
