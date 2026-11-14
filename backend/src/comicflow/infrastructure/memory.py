from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field

from comicflow.domain.models import ProjectRecord
from comicflow.infrastructure.generation_state import (
    GenerationStateStore,
    InMemoryGenerationStateStore,
)
from comicflow.production.pipeline import SYSTEM_CHARACTER_TEMPLATES, ProductionPipeline
from comicflow.providers.mock import MockTextProvider
from comicflow.providers.mock_media import (
    MockCompositionProvider,
    MockDynamicVisualProvider,
    MockLipSyncProvider,
    MockModerationProvider,
    MockTtsProvider,
)
from comicflow.providers.model_registry import MemoryRegistryRepository, ModelRegistry, SecretCipher
from comicflow.providers.runtime_config import ProviderConfigStore


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self._records: dict[str, ProjectRecord] = {}
        self._job_lock = asyncio.Lock()

    async def get(self, project_id: str) -> ProjectRecord | None:
        record = self._records.get(project_id)
        return deepcopy(record) if record else None

    async def list_projects(self) -> list[ProjectRecord]:
        return [deepcopy(record) for record in self._records.values()]

    async def save(
        self, record: ProjectRecord, *, outbox_event: dict[str, object] | None = None
    ) -> None:
        del outbox_event
        self._records[record.project["id"]] = deepcopy(record)

    async def find_by_job(self, job_id: str) -> ProjectRecord | None:
        for record in self._records.values():
            if any(job["id"] == job_id for job in record.jobs):
                return deepcopy(record)
        return None

    async def claim_job(self, job_id: str) -> ProjectRecord | None:
        async with self._job_lock:
            for record in self._records.values():
                for job in record.jobs:
                    if job["id"] == job_id and job["status"] in {"queued", "failed"}:
                        job["status"] = "running"
                        job["progress"] = 1
                        self._records[record.project["id"]] = deepcopy(record)
                        return deepcopy(record)
        return None


class InMemoryCharacterRepository:
    def __init__(self) -> None:
        self._characters = {item["id"]: deepcopy(item) for item in SYSTEM_CHARACTER_TEMPLATES}

    async def get(self, character_id: str) -> dict[str, object] | None:
        character = self._characters.get(character_id)
        return deepcopy(character) if character else None

    async def list(self) -> list[dict[str, object]]:
        return deepcopy(list(self._characters.values()))

    async def save(self, character: dict[str, object], *,
                   expected: dict[str, object] | None = None) -> None:
        if expected is not None and self._characters.get(str(character['id'])) != expected:
            from comicflow.domain.errors import DomainError
            raise DomainError('CHARACTER_VERSION_CONFLICT')
        self._characters[str(character["id"])] = deepcopy(character)

    async def delete(self, character_id: str) -> bool:
        if character_id not in self._characters:
            return False
        del self._characters[character_id]
        return True


@dataclass(frozen=True, slots=True)
class Runtime:
    pipeline: ProductionPipeline
    provider_config_store: ProviderConfigStore
    generation_state_store: GenerationStateStore
    model_registry: ModelRegistry = field(default_factory=lambda: ModelRegistry(
        MemoryRegistryRepository(), SecretCipher.ephemeral(),
    ))


def create_memory_runtime(generation_state_store: GenerationStateStore | None = None) -> Runtime:
    generation_state_store = generation_state_store or InMemoryGenerationStateStore()
    return Runtime(
        pipeline=ProductionPipeline(
            repository=InMemoryProjectRepository(),
            character_repository=InMemoryCharacterRepository(),
            text_provider=MockTextProvider(),
            dynamic_visual_provider=MockDynamicVisualProvider(),
            tts_provider=MockTtsProvider(),
            lip_sync_provider=MockLipSyncProvider(),
            composition_provider=MockCompositionProvider(),
            moderation_provider=MockModerationProvider(),
            generation_state_store=generation_state_store,
        ),
        provider_config_store=ProviderConfigStore(),
        generation_state_store=generation_state_store,
    )
