from __future__ import annotations

import asyncio
import hashlib
import logging
from copy import deepcopy
from typing import cast
from uuid import uuid4

from comicflow.domain.errors import DomainError
from comicflow.domain.models import Actor, CreateProject, JsonObject, ProjectRecord
from comicflow.infrastructure.generation_state import GenerationStateStore
from comicflow.production.audio_production import AudioProduction
from comicflow.production.character_assets import CharacterAssets
from comicflow.production.composition_jobs import CompositionJobs
from comicflow.production.image_jobs import ImageJobs
from comicflow.production.interfaces import (
    AssetStore,
    CharacterRepository,
    CompositionProvider,
    DynamicVisualProvider,
    LipSyncProvider,
    ModerationProvider,
    ProjectRepository,
    TextProvider,
    TtsProvider,
)
from comicflow.production.reference_images import generate_reference_image
from comicflow.production.story_scripts import StoryScripts
from comicflow.production.video_jobs import VideoJobs
from comicflow.production.video_preparation import VideoPreparation
from comicflow.production.video_resources import VideoResources
from comicflow.production.visual_styles import (
    resolve_style,
)
from comicflow.providers.error_mapping import map_provider_error

_logger = logging.getLogger(__name__)

SYSTEM_CHARACTER_TEMPLATES: tuple[JsonObject, ...] = (
    {
        "id": "system-urban-youth",
        "name": "都市青年",
        "appearance": "黑色短发，轮廓清晰",
        "clothing": "深色都市风外套",
        "personality": "克制、敏锐",
        "voice": {"provider": "yun-free", "voiceId": "male-calm", "language": "zh-CN"},
        "source": "system",
        "ownerType": "system",
    },
)


class ProductionPipeline:
    """Deep module for advancing and observing a ComicFlow production."""

    def __init__(
        self,
        repository: ProjectRepository,
        character_repository: CharacterRepository,
        text_provider: TextProvider,
        dynamic_visual_provider: DynamicVisualProvider,
        tts_provider: TtsProvider,
        lip_sync_provider: LipSyncProvider,
        composition_provider: CompositionProvider,
        asset_store: AssetStore | None = None,
        *,
        moderation_provider: ModerationProvider | None = None,
        initial_credits: int = 100,
        generation_state_store: GenerationStateStore | None = None,
        reference_image_provider: DynamicVisualProvider | None = None,
    ) -> None:
        self._repository = repository
        self._character_repository = character_repository
        self._text_provider = text_provider
        self._model_config_revision = 0
        self._dynamic_visual_provider = dynamic_visual_provider
        self._reference_image_provider = reference_image_provider
        self._tts_provider = tts_provider
        self._lip_sync_provider = lip_sync_provider
        self._composition_provider = composition_provider
        self._asset_store = asset_store
        self._moderation_provider = moderation_provider
        self._initial_credits = initial_credits
        self._generation_state_store = generation_state_store
        self._generation_locks: dict[str, asyncio.Lock] = {}
        self._presigned_url_cache: dict[str, tuple[str, float]] = {}
        from comicflow.infrastructure.database import SqlAlchemyProjectRepository
        from comicflow.infrastructure.video_jobs import MemoryVideoJobStore, SqlVideoJobStore

        self._video_job_store = (SqlVideoJobStore(repository._sessions)
                                 if isinstance(repository, SqlAlchemyProjectRepository)
                                 else MemoryVideoJobStore(repository))
        from comicflow.infrastructure.image_jobs import MemoryImageJobStore, SqlImageJobStore
        self._image_job_store = (SqlImageJobStore(repository._sessions)
                                if isinstance(repository, SqlAlchemyProjectRepository)
                                else MemoryImageJobStore(repository, character_repository))
        self._refresh_h3_writer()

    def set_text_provider(self, provider: TextProvider) -> None:
        """Replace the text Adapter at runtime without exposing its credentials."""
        self._text_provider = provider
        self._refresh_h3_writer()

    def set_reference_image_provider(self, provider: DynamicVisualProvider | None) -> None:
        self._reference_image_provider = provider

    def set_video_provider(self, provider: DynamicVisualProvider) -> None:
        self._dynamic_visual_provider = provider
        self._refresh_h3_writer()

    def _refresh_h3_writer(self) -> None:
        from comicflow.providers.h3_skill import H3SkillPromptWriter
        from comicflow.providers.minimax_h3 import MinimaxH3Provider

        if isinstance(self._dynamic_visual_provider, MinimaxH3Provider):
            complete = getattr(self._text_provider, 'compile_h3_prompt', None)
            self._dynamic_visual_provider.set_prompt_writer(
                H3SkillPromptWriter(complete) if callable(complete) else None
            )

    def get_provider_status(self) -> dict[str, str]:
        """Return the current provider types for observability."""
        image_provider = self._reference_image_provider
        image_provider = getattr(image_provider, 'active_provider', image_provider)
        image_adapter = type(image_provider).__name__
        image_model = str(getattr(image_provider, '_model', '') or '')
        image_protocol = str(getattr(image_provider, '_image_protocol', '') or '')
        if image_adapter == 'BailianImageProvider':
            from comicflow.providers.wanx_image import resolve_image_protocol

            try:
                image_protocol = resolve_image_protocol(image_model, image_protocol)
            except RuntimeError:
                image_protocol = 'invalid'
        elif image_adapter == 'OpenAIImageProvider':
            image_protocol = 'chat-completions-base64'
        return {
            "text": type(self._text_provider).__name__,
            "visual": type(self._dynamic_visual_provider).__name__,
            "image": image_adapter,
            "imageAdapter": image_adapter,
            "imageModel": image_model,
            "imageProtocol": image_protocol,
            "h3Prompt": str(
                getattr(self._dynamic_visual_provider, 'prompt_description', '未启用H3')
            ),
            "tts": type(self._tts_provider).__name__,
            "lipSync": type(self._lip_sync_provider).__name__,
            "composition": type(self._composition_provider).__name__,
        }

    async def _sync_generation_state(self, project: JsonObject) -> None:
        if self._generation_state_store is None:
            return
        session = project.get("generationSession")
        if not isinstance(session, dict):
            return
        state = deepcopy(session)
        state["mode"] = project.get("input", {}).get("mode")
        state["task"] = session.get("task", self._generation_task(project))
        state["projectVersion"] = project.get("version")
        state["partialText"] = project.get("generationPartialText", "")
        await self._generation_state_store.set_state(str(project["id"]), state)

    async def _append_generation_event(self, project_id: str, data: JsonObject) -> None:
        if self._generation_state_store is not None:
            await self._generation_state_store.append_event(project_id, data)

    @staticmethod
    def _generation_task(project: JsonObject) -> str:
        mode = project.get("input", {}).get("mode")
        stage = str(project.get("stage", ""))
        if mode == "automatic":
            return "story_expansion" if stage.startswith("story") else "automatic_production"
        if stage == "script-generating":
            return "script_outline"
        guided = project.get("generationSession", {}).get("guided", {})
        if isinstance(guided, dict) and guided.get("detailGenerated"):
            return "script_detail"
        return "guided_question"

    async def create_project(self, command: CreateProject) -> JsonObject:
        style_profile = resolve_style(command.style_preset_id)
        story = command.story.strip()
        if len(story) < 10:
            raise DomainError("STORY_TOO_SHORT")
        if not 30 <= command.duration_sec <= 90:
            raise DomainError("DURATION_OUT_OF_RANGE")

        project_id = f"prj_{uuid4().hex[:12]}"
        guest_id = f"gst_{uuid4().hex[:12]}"
        estimated_shots = (
            6 if command.duration_sec <= 30 else 9 if command.duration_sec <= 60 else 11
        )
        estimate = {"shots": estimated_shots, "creditMin": 20, "creditMax": 28}
        imported_source = command.mode in {"import_story", "import_script"}
        project: JsonObject = {
            "id": project_id,
            "stage": "story-generated" if imported_source else "story",
            "version": 1,
            "input": {
                "inputType": command.input_type,
                "story": story,
                "durationSec": command.duration_sec,
                "mode": command.mode,
            },
            "ownerUserId": None,
            "visualStyleProfile": style_profile,
            "exportManifest": None,
            "generatedStoryText": story if imported_source else None,
            "storyTextVersion": 1 if imported_source else 0,
            "script": None,
            "creditLedger": [{"type": "grant", "amount": self._initial_credits}],
            "estimate": estimate,
            "scriptVersions": [],
            "generationSession": {
                "id": f"gen_{uuid4().hex[:12]}",
                "projectId": project_id,
                "mode": command.mode,
                "stage": "story-generated" if imported_source else "story",
                "status": "ready",
                "retryCount": 0,
                "guided": {
                    "questionCount": 0,
                    "maxQuestions": 9,
                    "currentQuestion": "",
                    "transcript": [],
                    "done": command.mode != "guided",
                    "detailGenerated": False,
                    "skippedTargets": [],
                },
            },
        }
        guest_session = {"id": guest_id, "projectId": project_id}
        await self._repository.save(ProjectRecord(project=project, guest_session=guest_session))
        await self._sync_generation_state(project)
        return {
            "project": deepcopy(project),
            "guestSession": deepcopy(guest_session),
            "estimate": deepcopy(estimate),
        }

    async def list_projects(self) -> list[JsonObject]:
        """Return persisted project snapshots for local recovery and project pickers."""
        snapshots = [record.snapshot() for record in await self._repository.list_projects()]
        for snapshot in snapshots:
            await self._enrich_snapshot_with_asset_urls(snapshot)
        return snapshots

    async def upload_reference_image(
        self,
        project_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        user_id: str | None = None,
    ) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        owner = project.get("ownerUserId")
        if owner is not None and owner != user_id:
            raise DomainError("PROJECT_ACCESS_DENIED")
        allowed = {"image/png", "image/jpeg", "image/webp"}
        if content_type.lower() not in allowed:
            raise DomainError("REFERENCE_IMAGE_TYPE_INVALID")
        if not content or len(content) > 10 * 1024 * 1024:
            raise DomainError("REFERENCE_IMAGE_SIZE_INVALID")
        digest = hashlib.sha256(content).hexdigest()
        asset_id = f"ref_{digest[:16]}"
        object_key = f"projects/{project_id}/references/{asset_id}-{filename or 'reference'}"
        asset: JsonObject = {
            "id": asset_id,
            "type": "reference-image",
            "mediaType": content_type.lower(),
            "sizeBytes": len(content),
            "sha256": digest,
            "objectKey": object_key,
            "filename": filename or "reference-image",
            "valid": True,
        }
        previous = project.get("referenceImage")
        if isinstance(previous, dict):
            previous["valid"] = False
        history = project.setdefault("referenceImages", [])
        if isinstance(history, list) and history and isinstance(history[-1], dict):
            history[-1]["valid"] = False
        if self._asset_store is not None:
            await self._asset_store.put_bytes(object_key, content, content_type.lower())
            asset["downloadUrl"] = await self._asset_store.presigned_get_url(object_key)
        project["referenceImage"] = asset
        history.append(deepcopy(asset))
        project["version"] += 1
        await self._repository.save(record)
        return {"asset": deepcopy(asset), "projectVersion": project["version"]}

    def _story_scripts(self) -> StoryScripts:
        # Build from this request's provider/revision; locks and storage keep their lifetime.
        return StoryScripts(
            repository=self._repository, characters=self._character_repository,
            text_provider=self._text_provider, moderation_provider=self._moderation_provider,
            locks=self._generation_locks, model_config_revision=self._model_config_revision,
            sync_generation_state=self._sync_generation_state,
            append_generation_event=self._append_generation_event,
            create_character=self.create_character,
        )

    async def _save_script_mutation(self, record: ProjectRecord) -> JsonObject:
        # Character binding edits share the same script version/state transition.
        return await self._story_scripts().save_script_mutation(record)

    async def generate_story_text(
        self, project_id: str, *, idempotency_key: str | None = None
    ) -> JsonObject:
        return await self._story_scripts().generate_story_text(
            project_id, idempotency_key=idempotency_key
        )

    async def update_story_text(
        self, project_id: str, story_text: str, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().update_story_text(
            project_id, story_text, expected_version=expected_version
        )

    async def split_script(self, project_id: str) -> JsonObject:
        return await self._story_scripts().split_script(
            project_id
        )

    async def preview_script(self, project_id: str) -> JsonObject:
        return await self._story_scripts().preview_script(
            project_id
        )

    async def commit_script_preview(
        self, project_id: str, script: JsonObject, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().commit_script_preview(
            project_id, script, expected_version=expected_version
        )

    async def generate_script(
        self, project_id: str, *, idempotency_key: str | None = None
    ) -> JsonObject:
        return await self._story_scripts().generate_script(
            project_id, idempotency_key=idempotency_key
        )

    async def _presigned_url_cached(self, object_key: str) -> str:
        """Return a cached presigned URL if still valid, else generate and cache."""
        now = asyncio.get_running_loop().time()
        if object_key in self._presigned_url_cache:
            url, expires_at = self._presigned_url_cache[object_key]
            if now < expires_at:
                return url
        if self._asset_store is None:
            raise RuntimeError("ASSET_STORE_NOT_CONFIGURED")
        url = await self._asset_store.presigned_get_url(object_key, expires_in=900)
        self._presigned_url_cache[object_key] = (url, now + 870)
        return url

    async def _enrich_snapshot_with_asset_urls(self, snapshot: JsonObject) -> None:
        """Enrich playable current and candidate assets with URLs in-place."""
        if self._asset_store is None:
            return
        for kind in ("visualAssets", "audioAssets", "lipSyncAssets"):
            for asset in snapshot.get(kind, []):
                if (asset.get("valid") or asset.get("status") == "candidate") \
                        and "objectKey" in asset:
                    asset["downloadUrl"] = await self._presigned_url_cached(asset["objectKey"])
                # Shot rails and the storyboard show the adopted video's first frame.
                poster_key = asset.get("firstFrameObjectKey")
                if kind == "visualAssets" and asset.get("valid") and isinstance(poster_key, str):
                    asset["posterUrl"] = await self._presigned_url_cached(poster_key)

    async def get_snapshot(self, project_id: str, *, user_id: str | None = None) -> JsonObject:
        record = await self._require_record(project_id)
        owner = record.project.get("ownerUserId")
        if owner is not None and owner != user_id:
            raise DomainError("PROJECT_ACCESS_DENIED")
        snapshot = record.snapshot()
        await self._enrich_snapshot_with_asset_urls(snapshot)
        return snapshot

    def video_resources(self) -> VideoResources:
        return VideoResources(self._repository, self._asset_store)

    async def claim_project(self, project_id: str, *, user_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        owner = record.project.get("ownerUserId")
        if owner is not None and owner != user_id:
            raise DomainError("PROJECT_ACCESS_DENIED")
        record.project["ownerUserId"] = user_id
        await self._repository.save(record)
        snapshot = record.snapshot()
        await self._enrich_snapshot_with_asset_urls(snapshot)
        return snapshot

    async def project_credits(self, project_id: str, *, user_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        owner = record.project.get("ownerUserId")
        if owner is not None and owner != user_id:
            raise DomainError("PROJECT_ACCESS_DENIED")
        ledger = record.project.get("creditLedger", [])
        available = sum(int(event.get("amount", 0)) for event in ledger)
        return {"available": available, "ledger": deepcopy(ledger)}

    def _character_assets(self) -> CharacterAssets:
        # Request-scoped providers can change; storage, locks and URL cache retain their lifetime.
        return CharacterAssets(
            repository=self._repository, characters=self._character_repository,
            image_provider=self._reference_image_provider, text_provider=self._text_provider,
            asset_store=self._asset_store, locks=self._generation_locks,
            presign=self._presigned_url_cached,
        )

    async def list_character_templates(self) -> list[JsonObject]:
        return await self._character_assets().list_character_templates()

    async def list_project_characters(self, project_id: str) -> list[JsonObject]:
        return await self._character_assets().list_project_characters(
            project_id
        )

    async def sync_project_characters(
        self, project_id: str, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().sync_project_characters(
            project_id, expected_version=expected_version
        )

    async def preview_character_prompt(
        self, project_id: str, *, fields: JsonObject, instructions: str,
        character_id: str | None, expected_version: int, expected_revision: int,
        purpose: str = 'full', output_fields: list[str] | None = None,
    ) -> JsonObject:
        return await self._character_assets().preview_character_prompt(
            project_id, fields=fields, instructions=instructions, character_id=character_id,
            expected_version=expected_version, expected_revision=expected_revision,
            purpose=purpose, output_fields=output_fields,
        )

    async def save_project_character(
        self, project_id: str, input_data: JsonObject, *, character_id: str | None = None
    ) -> JsonObject:
        return await self._character_assets().save_project_character(
            project_id, input_data, character_id=character_id
        )

    async def create_character(
        self, input_data: JsonObject, *, actor: Actor, project_id: str | None = None
    ) -> JsonObject:
        return await self._character_assets().create_character(
            input_data, actor=actor, project_id=project_id
        )

    async def update_character(
        self, character_id: str, input_data: JsonObject, *, actor: Actor
    ) -> JsonObject:
        return await self._character_assets().update_character(
            character_id, input_data, actor=actor
        )

    async def delete_character(self, character_id: str, *, actor: Actor) -> None:
        return await self._character_assets().delete_character(
            character_id, actor=actor
        )

    async def assign_shot_characters(
        self,
        project_id: str,
        shot_id: str,
        character_ids: list[str],
        *,
        expected_version: int,
    ) -> JsonObject:
        if len(character_ids) > 2:
            raise DomainError("SHOT_CHARACTER_LIMIT")
        if len(set(character_ids)) != len(character_ids):
            raise DomainError("SHOT_CHARACTER_DUPLICATE")
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        shot = next(
            (item for item in project.get("script", {}).get("shots", []) if item["id"] == shot_id),
            None,
        )
        if shot is None:
            raise DomainError("SHOT_NOT_FOUND")
        names = []
        for character_id in character_ids:
            character = await self._character_repository.get(character_id)
            if character is None:
                raise DomainError("CHARACTER_NOT_FOUND")
            if character.get("source") == "temporary" and character.get("projectId") != project_id:
                raise DomainError("CHARACTER_ACCESS_DENIED")
            names.append(character['name'])
        project.setdefault('scriptVersions', []).append({
            'version': project['version'], 'projectId': project_id,
            'script': deepcopy(project['script']),
        })
        shot["characterIds"] = list(character_ids)
        shot['characters'] = names
        project.pop('scriptConfirmedVersion', None)
        await self._save_script_mutation(record)
        return {"characterIds": list(character_ids), "projectVersion": project["version"]}

    async def get_shot_character_input(self, project_id: str, shot_id: str) -> list[JsonObject]:
        return await self._video_preparation().character_inputs(project_id, shot_id)
    async def _prepare_shot_visual(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> tuple[ProjectRecord, JsonObject, list[JsonObject], str | None]:
        return await self._video_preparation().prepare(
            project_id, shot_id, expected_version=expected_version)
    async def preview_shot_visual(
        self, project_id: str, shot_id: str, *, expected_version: int,
        continuity_mode: str = 'auto',
    ) -> JsonObject:
        return await self._video_preparation().preview(
            project_id, shot_id, expected_version=expected_version, continuity_mode=continuity_mode)

    def _video_preparation(self) -> VideoPreparation:
        return VideoPreparation(
            self._repository, self._character_repository, self._dynamic_visual_provider,
            self._text_provider, self._asset_store, self._model_config_revision,
            self._presigned_url_cached,
        )
    def _video_jobs(self) -> VideoJobs:
        return VideoJobs(
            store=self._video_job_store, preparation=self._video_preparation(),
            repository=self._repository, provider=self._dynamic_visual_provider,
            text_provider=self._text_provider, asset_store=self._asset_store,
            model_config_revision=self._model_config_revision,
        )
    async def request_video_job(
        self, project_id: str, shot_id: str, *, expected_version: int,
        operation_id: str, preflight_fingerprint: str | None = None,
        continuity_mode: str = 'auto',
    ) -> JsonObject:
        from comicflow.production.video_jobs import public_job
        job = await self._video_jobs().request(project_id, shot_id,
            expected_version=expected_version, operation_id=operation_id,
            preflight_fingerprint=preflight_fingerprint, continuity_mode=continuity_mode)
        return public_job(job)

    async def list_video_jobs(self, project_id: str) -> list[JsonObject]:
        from comicflow.production.video_jobs import public_job
        jobs = await self._video_job_store.list(project_id)
        return [public_job(j) for j in sorted(jobs, key=lambda j: j['createdAt'], reverse=True)]

    async def get_video_job(self, project_id: str, job_id: str) -> JsonObject:
        from comicflow.production.video_jobs import public_job
        return public_job(await self._video_jobs().require(project_id, job_id))

    async def run_video_job(self, job_id: str) -> JsonObject:
        from comicflow.production.video_jobs import public_job
        return public_job(await self._video_jobs().run(job_id))

    async def recover_video_job(self, project_id: str, job_id: str,
                                task_id: str | None = None) -> JsonObject:
        from comicflow.production.video_jobs import public_job
        return public_job(await self._video_jobs().recover(project_id, job_id, task_id))

    async def adopt_video_job(self, project_id: str, job_id: str) -> JsonObject:
        from comicflow.production.video_jobs import public_job
        return public_job(await self._video_jobs().adopt(project_id, job_id))

    async def generate_shot_visual(
        self, project_id: str, shot_id: str, *, expected_version: int,
        preflight_fingerprint: str | None = None,
    ) -> JsonObject:
        jobs = self._video_jobs()
        record = await self._require_record(project_id)
        current_id = next((a['id'] for a in record.project.get('visualAssets', [])
                           if a.get('shotId') == shot_id and a.get('valid')), 'none')
        job = await jobs.request(project_id, shot_id, expected_version=expected_version,
            operation_id=f'sync-{expected_version}-{self._model_config_revision}-{current_id}',
            preflight_fingerprint=preflight_fingerprint)
        completed = await jobs.run(job['id'])
        if completed['status'] == 'succeeded':
            return {**deepcopy(completed['result']), 'jobId': job['id'],
                    'awaitingAdoption': not completed['result']['asset'].get('valid', False)}
        raise DomainError(completed.get('error') or 'VIDEO_JOB_ACTIVE', {
            **(completed.get('errorDetail') or {}),
            **({'taskId': completed['taskId']} if completed.get('taskId') else {}),
        })

    def _audio_production(self) -> AudioProduction:
        return AudioProduction(
            self._repository, self._tts_provider, self._lip_sync_provider, self._asset_store,
        )

    async def generate_shot_audio(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> JsonObject:
        return await self._audio_production().generate_shot_audio(
            project_id, shot_id, expected_version=expected_version,
        )

    async def _prepare_native_audio(
        self, record: ProjectRecord, shot: JsonObject, visual: JsonObject, expected_version: int,
    ) -> JsonObject:
        return await self._audio_production()._prepare_native_audio(
            record, shot, visual, expected_version,
        )

    async def get_generation_session(self, project_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        session = record.project.setdefault(
            "generationSession",
            {
                "id": f"gen_{uuid4().hex[:12]}",
                "projectId": project_id,
                "mode": record.project["input"]["mode"],
                "stage": record.project["stage"],
                "status": "ready",
                "retryCount": 0,
            },
        )
        session["stage"] = record.project["stage"]
        await self._repository.save(record)
        await self._sync_generation_state(record.project)
        return deepcopy(session)

    async def ask_guided_question(self, project_id: str) -> JsonObject:
        return await self._story_scripts().ask_guided_question(
            project_id
        )

    async def answer_guided_question(self, project_id: str, answer: str) -> JsonObject:
        return await self._story_scripts().answer_guided_question(
            project_id, answer
        )

    async def skip_guided_question(self, project_id: str) -> JsonObject:
        return await self._story_scripts().skip_guided_question(
            project_id
        )

    async def generate_detailed_script(self, project_id: str) -> JsonObject:
        return await self._story_scripts().generate_detailed_script(
            project_id
        )

    async def _wait_for_video_adoption(self, project_id: str, asset: JsonObject) -> JsonObject:
        record = await self._require_record(project_id)
        session = record.project.setdefault('generationSession', {})
        session.update(status='paused', stage=record.project['stage'], lastError=None,
                       pauseReason='video-awaiting-adoption', waitingJobId=asset['jobId'],
                       waitingShotId=asset['shotId'])
        await self._repository.save(record)
        await self._sync_generation_state(record.project)
        return deepcopy(session)

    async def update_generation_session(self, project_id: str, action: str) -> JsonObject:
        record = await self._require_record(project_id)
        session = record.project.setdefault("generationSession", {})
        status = str(session.get("status", "ready"))
        allowed = {
            "pause": {"ready", "running", "waiting-retry"},
            "resume": {"paused", "waiting-retry"},
            "cancel": {"ready", "running", "paused", "waiting-retry"},
            "retry": {"ready", "waiting-retry", "script-failed"},
        }
        if action not in allowed or status not in allowed[action]:
            raise DomainError("SESSION_ACTION_INVALID")
        if action == "pause":
            session["status"] = "paused"
        elif action == "resume":
            waiting_id = session.get('waitingJobId')
            if waiting_id:
                waiting = await self._video_jobs().require(project_id, waiting_id)
                assets = [a for a in record.project.get('visualAssets', [])
                          if a.get('shotId') == waiting['shotId']]
                # A newer adopted candidate may replace the one this session paused for.
                if not assets or not assets[-1].get('valid'):
                    raise DomainError('VIDEO_JOB_AWAITING_ADOPTION', {'jobId': waiting_id})
                if record.project['stage'] in {'visual-completed', 'audio-completed'}:
                    record.project['stage'] = 'storyboard-ready'
                    session['stage'] = 'storyboard-ready'
            for key in ('pauseReason', 'waitingJobId', 'waitingShotId'):
                session.pop(key, None)
            session["status"] = "ready"
        elif action == "cancel":
            session["status"] = "cancelled"
            record.project["stage"] = "cancelled"
        elif action == "retry":
            session["status"] = "ready"
            session["retryCount"] = int(session.get("retryCount", 0)) + 1
            await self._repository.save(
                record,
                outbox_event={
                    "topic": "production.generation.advance",
                    "payload": {
                        "projectId": project_id,
                        "sessionId": session.get("id"),
                        "modelConfigRevision": self._model_config_revision,
                    },
                },
            )
            return deepcopy(session)
        await self._repository.save(record)
        await self._sync_generation_state(record.project)
        return deepcopy(session)

    async def advance_generation_session(self, project_id: str) -> JsonObject:
        lock = self._generation_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            return await self._advance_generation_session(project_id)

    async def _advance_generation_session(self, project_id: str) -> JsonObject:
        """Advance one automatic-production checkpoint using persisted project state."""
        record = await self._require_record(project_id)
        project = record.project
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        if session.get("mode", project.get("input", {}).get("mode")) != "automatic":
            return deepcopy(session)
        if session.get("status") in {"paused", "cancelled", "completed"}:
            return deepcopy(session)

        stage = str(project.get("stage", "story"))
        if stage == "story-generated":
            session.update({"stage": stage, "status": "ready", "lastError": None})
            await self._repository.save(record)
            await self._sync_generation_state(record.project)
            return deepcopy(session)
        if stage in {'storyboard-ready', 'visual-completed', 'audio-completed'}:
            latest_assets = {a.get('shotId'): a for a in project.get('visualAssets', [])}
            for shot in project.get('script', {}).get('shots', []):
                latest = latest_assets.get(shot['id'], {})
                if latest.get('status') == 'candidate' and latest.get('jobId'):
                    return await self._wait_for_video_adoption(project_id, latest)
        session.update({"status": "running", "lastError": None})
        try:
            if stage == "script-completed":
                await self.confirm_script(project_id, expected_version=int(project["version"]))
                record = await self._require_record(project_id)
                project = record.project
                session = cast(JsonObject, project.setdefault("generationSession", session))
                project["stage"] = "storyboard-ready"
            elif stage == "storyboard-ready":
                shots = list(project.get("script", {}).get("shots", []))
                version = int(project["version"])
                completed_visual = {
                    str(asset.get("shotId"))
                    for asset in project.get("visualAssets", [])
                    if asset.get("valid")
                }
                for shot in shots:
                    if str(shot["id"]) in completed_visual:
                        continue
                    result = await self.generate_shot_visual(
                        project_id, str(shot["id"]), expected_version=version
                    )
                    if result.get('awaitingAdoption'):
                        return await self._wait_for_video_adoption(project_id, result['asset'])
                    completed_visual.add(str(result["asset"]["shotId"]))
                record = await self._require_record(project_id)
                project = record.project
                session = cast(JsonObject, project.setdefault("generationSession", session))
                project["stage"] = "visual-completed"
            elif stage == "visual-completed":
                shots = list(project.get("script", {}).get("shots", []))
                version = int(project["version"])
                native_shots = {
                    str(asset.get("shotId"))
                    for asset in project.get("visualAssets", [])
                    if asset.get("valid") and asset.get("provider") == "minimax"
                    and asset.get("mediaType") == "video"
                }
                completed_audio = {
                    str(asset.get("shotId"))
                    for asset in project.get("audioAssets", [])
                    if asset.get("valid")
                }
                for shot in shots:
                    if str(shot["id"]) in completed_audio or str(shot["id"]) in native_shots:
                        continue
                    result = await self.generate_shot_audio(
                        project_id, str(shot["id"]), expected_version=version
                    )
                    audio_asset = result.get("asset")
                    if isinstance(audio_asset, dict):
                        completed_audio.add(str(audio_asset["shotId"]))
                record = await self._require_record(project_id)
                project = record.project
                session = cast(JsonObject, project.setdefault("generationSession", session))
                project["stage"] = "audio-completed"
            elif stage == "audio-completed":
                await self.request_composition(
                    project_id,
                    expected_version=int(project["version"]),
                    idempotency_key=f"generation-{project_id}",
                )
                record = await self._require_record(project_id)
                project = record.project
                session = cast(JsonObject, project.setdefault("generationSession", session))
                project["stage"] = "composition-queued"
                session.update({"stage": "composition-queued", "status": "running"})
                await self._repository.save(record)
                return deepcopy(session)
            elif stage == "composition-queued":
                job = next(
                    (
                        item
                        for item in record.jobs
                        if item.get("type") == "composition"
                        and item.get("idempotencyKey") == f"generation-{project_id}"
                    ),
                    None,
                )
                if job is None or job.get("status") in {"queued", "running"}:
                    session.update({"stage": stage, "status": "running"})
                    await self._repository.save(record)
                    return deepcopy(session)
                if job.get("status") == "failed":
                    session.update(
                        {
                            "stage": stage,
                            "status": "waiting-retry",
                            "lastError": job.get("error", "COMPOSITION_FAILED"),
                        }
                    )
                    await self._repository.save(record)
                    return deepcopy(session)
                if job.get("status") == "succeeded":
                    project["stage"] = "exported"
            elif stage == "exported":
                session.update({"stage": stage, "status": "completed"})
                await self._repository.save(record)
                return deepcopy(session)
            else:
                session.update({"stage": stage, "status": "waiting-retry"})
                await self._repository.save(record)
                return deepcopy(session)
        except (DomainError, RuntimeError) as error:
            record = await self._require_record(project_id)
            project = record.project
            session = cast(JsonObject, project.setdefault("generationSession", session))
            session.update(
                {
                    "stage": project.get("stage", stage),
                    "status": "waiting-retry",
                    "lastError": str(error),
                }
            )
            await self._repository.save(record)
            return deepcopy(session)

        session.update({"stage": project["stage"], "status": "running"})
        await self._repository.save(
            record,
            outbox_event={
                "topic": "production.generation.advance",
                "payload": {
                    "projectId": project_id,
                    "sessionId": session.get("id"),
                    "modelConfigRevision": self._model_config_revision,
                },
            },
        )
        return deepcopy(session)

    async def list_script_versions(self, project_id: str) -> list[JsonObject]:
        return await self._story_scripts().list_script_versions(
            project_id
        )

    async def duplicate_project(self, project_id: str) -> JsonObject:
        source = await self._require_record(project_id)
        input_data = deepcopy(source.project["input"])
        return await self.create_project(
            CreateProject(
                input_type=input_data["inputType"],
                story=input_data["story"],
                duration_sec=input_data["durationSec"],
                mode=input_data["mode"],
            )
        )

    async def regenerate_shot(
        self,
        project_id: str,
        shot_id: str,
        *,
        scope: str,
        expected_version: int,
    ) -> JsonObject:
        """Regenerate one shot scope while preserving unrelated valid assets."""
        if scope not in {"visual", "audio", "lipsync", "shot"}:
            raise DomainError("REGENERATION_SCOPE_INVALID")
        if scope == "visual":
            result = await self.generate_shot_visual(
                project_id, shot_id, expected_version=expected_version
            )
            return {**result, "scope": scope}
        if scope == "audio" or scope == "shot":
            current_version = expected_version
            visual_result: JsonObject | None = None
            if scope == "shot":
                visual_result = await self.generate_shot_visual(
                    project_id, shot_id, expected_version=current_version
                )
                if visual_result.get('awaitingAdoption'):
                    return {**visual_result, 'scope': scope, 'visual': visual_result}
                current_version = int(visual_result["projectVersion"])
            result = await self.generate_shot_audio(
                project_id, shot_id, expected_version=current_version
            )
            return {
                **result,
                "scope": scope,
                **({"visual": visual_result} if visual_result else {}),
            }

        return await self._audio_production().regenerate_lip_sync(
            project_id, shot_id, expected_version=expected_version,
        )

    def _composition_jobs(self) -> CompositionJobs:
        return CompositionJobs(
            self._repository, self._composition_provider, self._asset_store,
            model_config_revision=self._model_config_revision,
        )

    @staticmethod
    def _composition_readiness(project: JsonObject) -> JsonObject:
        return CompositionJobs._composition_readiness(project)

    async def request_composition(
        self, project_id: str, *, expected_version: int, idempotency_key: str | None = None,
        shot_ids: list[str] | None = None,
        shot_trims: JsonObject | None = None,
    ) -> JsonObject:
        return await self._composition_jobs().request_composition(
            project_id, expected_version=expected_version, idempotency_key=idempotency_key,
            shot_ids=shot_ids,
            shot_trims=shot_trims,
        )

    async def run_job(self, job_id: str) -> JsonObject:
        return await self._composition_jobs().run_job(job_id)

    async def get_export_manifest(
        self, project_id: str, *, job_id: str | None = None,
    ) -> JsonObject:
        return await self._composition_jobs().get_export_manifest(project_id, job_id=job_id)

    async def cancel_job(self, job_id: str) -> JsonObject:
        return await self._composition_jobs().cancel_job(job_id)

    async def update_script(
        self, project_id: str, script: JsonObject, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().update_script(
            project_id, script, expected_version=expected_version
        )

    async def _reference_image(self, shot: JsonObject) -> JsonObject:
        return await generate_reference_image(
            shot, provider=self._reference_image_provider, asset_store=self._asset_store,
            presign=self._presigned_url_cached,
        )

    def _image_jobs(self) -> ImageJobs:
        return ImageJobs(store=self._image_job_store, characters=self._character_assets(),
            repository=self._repository, character_repository=self._character_repository,
            provider=self._reference_image_provider, asset_store=self._asset_store,
            model_config_revision=self._model_config_revision)

    async def approve_character_reference_board(self, project_id: str, character_id: str,
                                                 candidate_id: str, *,
                                                 expected_version: int) -> JsonObject:
        return await self._image_job_store.approve_board(
            project_id, character_id, candidate_id, expected_version)

    async def request_image_job(self, project_id: str, character_id: str, *,
                                expected_version: int, operation_id: str,
                                purpose: str = 'candidate', force: bool = False) -> JsonObject:
        from comicflow.production.image_jobs import public_job
        return public_job(await self._image_jobs().request(project_id, character_id,
            expected_version=expected_version, operation_id=operation_id, purpose=purpose,
            force=force))

    async def list_image_jobs(self, project_id: str) -> list[JsonObject]:
        jobs = self._image_jobs()
        return [await jobs.public(j) for j in await self._image_job_store.list(project_id)]

    async def get_image_job(self, project_id: str, job_id: str) -> JsonObject:
        jobs = self._image_jobs()
        return await jobs.public(await jobs.require(project_id, job_id))

    async def run_image_job(self, job_id: str) -> JsonObject:
        from comicflow.production.image_jobs import public_job
        return public_job(await self._image_jobs().run(job_id))

    async def recover_image_job(self, project_id: str, job_id: str) -> JsonObject:
        from comicflow.production.image_jobs import public_job
        return public_job(await self._image_jobs().recover(project_id, job_id))

    async def _run_image_compat(self, project_id: str, character_id: str, *,
                                expected_version: int, purpose: str,
                                force: bool = False) -> JsonObject:
        jobs = self._image_jobs()
        job = await jobs.request(project_id, character_id, expected_version=expected_version,
            operation_id=f'legacy-{purpose}-{uuid4().hex}', purpose=purpose,
            force=force)
        job = await jobs.run(job['id'])
        if job['status'] == 'succeeded' and job.get('applied', True):
            return {**job['result'], 'jobId': job['id']}
        if job.get('error') == 'IMAGE_JOB_INPUT_CHANGED':
            raise DomainError('CHARACTER_VERSION_CONFLICT', {'jobId': job['id']})
        if purpose == 'views' and job.get('results'):
            raise DomainError('REFERENCE_VIEWS_PARTIAL', {
                'jobId': job['id'], 'generatedViews': list(job['results'])})
        raise DomainError(job.get('error') or 'IMAGE_JOB_BUSY', {'jobId': job['id']})

    async def generate_character_reference_candidate(
        self, project_id: str, character_id: str, *, expected_version: int
    ) -> JsonObject:
        return await self._run_image_compat(project_id, character_id,
            expected_version=expected_version, purpose='candidate')

    async def approve_character_reference_candidate(
        self,
        project_id: str,
        character_id: str,
        candidate_id: str,
        *,
        expected_version: int,
    ) -> JsonObject:
        return await self._character_assets().approve_character_reference_candidate(
            project_id, character_id, candidate_id, expected_version=expected_version
        )

    async def generate_character_reference_views(
        self,
        project_id: str,
        character_id: str,
        *,
        expected_version: int,
        force: bool = False,
    ) -> JsonObject:
        return await self._run_image_compat(project_id, character_id,
            expected_version=expected_version, purpose='views', force=force)

    async def generate_project_reference(
        self, project_id: str, kind: str, target_id: str, *, expected_version: int
    ) -> JsonObject:
        if kind == 'characters':
            record = await self._require_record(project_id)
            self._require_version(record.project, expected_version)
            character = await self._character_repository.get(target_id)
            if not character or character.get('projectId') != project_id:
                raise DomainError('CHARACTER_ACCESS_DENIED')
            if character.get('referenceImageObjectKey') or (
                character.get('referenceImageMediaType') == 'image'
                and character.get('referenceImageUrl')):
                return {'reused': True, 'projectVersion': record.project['version']}
            # Legacy direct approval still uses the submission journal.
            candidate = await self.generate_character_reference_candidate(
                project_id, target_id, expected_version=expected_version)
            result = await self.approve_character_reference_candidate(
                project_id, target_id, candidate['candidate']['id'],
                expected_version=candidate['projectVersion'])
            return {'reused': False, 'projectVersion': result['projectVersion']}
        # Use fine-grained lock per target instead of per project
        lock_key = f"{project_id}:{kind}:{target_id}"
        lock = self._generation_locks.setdefault(lock_key, asyncio.Lock())

        # Try to acquire lock without blocking
        if not lock.locked():
            async with lock:
                return await self._do_generate_reference(
                    project_id, kind, target_id, expected_version=expected_version
                )

        # Lock is held - check if image already exists to avoid false positives
        record = await self._require_record(project_id)
        target = self._get_scene_by_id(record.project.get('script') or {}, target_id)
        prefix = 'backgroundImage'

        if target and (
            target.get(prefix + 'ObjectKey')
            or (target.get(prefix + 'MediaType') == 'image' and target.get(prefix + 'Url'))
        ):
            # Image exists - return it even though lock is held
            record = await self._require_record(project_id)
            return {'reused': True, 'projectVersion': record.project['version']}

        # Lock held and no image - truly in progress
        raise DomainError('GENERATION_IN_PROGRESS')

    async def _do_generate_reference(
        self, project_id: str, kind: str, target_id: str, *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        target = self._get_scene_by_id(record.project.get('script') or {}, target_id)
        prefix = 'backgroundImage'
        if target is None:
            raise DomainError('SCENE_NOT_FOUND')
        if not target.get('location') or not target.get('time'):
            raise DomainError('SCENE_FIELDS_REQUIRED')
        # Reuse any persisted image identity. Some compatible providers return a
        # source URL without an object key, and regenerating it would spend quota.
        if target.get(prefix + 'ObjectKey') or (
            target.get(prefix + 'MediaType') == 'image' and target.get(prefix + 'Url')
        ):
            return {'reused': True, 'projectVersion': record.project['version']}
        try:
            ref = await self._generate_scene_background(
                target, project_id, style_profile=record.project.get('visualStyleProfile'))
        except RuntimeError as error:
            raise DomainError(map_provider_error(str(error))) from error
        current = await self._require_record(project_id)
        self._require_version(current.project, expected_version)
        target.update({prefix + 'Url': ref['url'], prefix + 'ObjectKey': ref['objectKey'],
                       prefix + 'MediaType': 'image'})
        if isinstance(ref.get('skillExecution'), dict):
            target[prefix + 'SkillExecution'] = deepcopy(ref['skillExecution'])
        if isinstance(ref.get('styleSnapshot'), dict):
            target[prefix + 'StyleSnapshot'] = deepcopy(ref['styleSnapshot'])
        record.project['version'] += 1
        await self._repository.save(record)
        return {'reused': False, 'projectVersion': record.project['version']}

    async def _generate_character_reference(
        self, character: JsonObject, project_id: str, *, generation_id: str | None = None,
        style_profile: JsonObject | None = None,
    ) -> JsonObject:
        return await self._character_assets()._generate_character_reference(
            character, project_id, generation_id=generation_id, style_profile=style_profile
        )

    async def _generate_scene_background(
        self, scene: JsonObject, project_id: str, *, style_profile: JsonObject | None = None,
    ) -> JsonObject:
        styled = style_profile is not None
        location = scene.get('location', '')
        time = scene.get('time', '')
        weather = scene.get('weather', '')
        lighting = scene.get('lighting', '')

        base_info = f"地点：{location}。时间：{time}。"
        if weather:
            base_info += f"天气：{weather}。"
        if lighting:
            base_info += f"光线：{lighting}。"

        return await self._reference_image({
            "id": f"{project_id}_scene_bg_{scene['id']}",
            "imagePurpose": "scene-background", "durationSec": 4,
            "styleSnapshot": deepcopy(style_profile),
            "visualDescription": scene.get('backgroundImagePrompt') or (
                f"{base_info}\n无人场景背景图，广角全景构图，清晰呈现空间布局和环境氛围，"
                "无人物、无动物、无文字、无水印。" if styled else
                f"{base_info}\n写实电影感无人场景背景参考图，广角全景，环境细节清晰，"
                "光线统一，无人物、无文字水印。"
            ),
        })

    async def confirm_script(self, project_id: str, *, expected_version: int) -> JsonObject:
        return await self._story_scripts().confirm_script(
            project_id, expected_version=expected_version
        )

    async def add_shot(
        self, project_id: str, shot: JsonObject, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().add_shot(
            project_id, shot, expected_version=expected_version
        )

    async def duplicate_shot(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().duplicate_shot(
            project_id, shot_id, expected_version=expected_version
        )

    async def delete_shot(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().delete_shot(
            project_id, shot_id, expected_version=expected_version
        )

    async def reorder_shots(
        self, project_id: str, shot_ids: list[str], *, expected_version: int
    ) -> JsonObject:
        return await self._story_scripts().reorder_shots(
            project_id, shot_ids, expected_version=expected_version
        )

    async def _require_record(self, project_id: str) -> ProjectRecord:
        record = await self._repository.get(project_id)
        if record is None:
            raise DomainError("PROJECT_NOT_FOUND")
        return record

    @staticmethod
    def _require_version(project: JsonObject, expected_version: int) -> None:
        if project["version"] != expected_version:
            raise DomainError("VERSION_CONFLICT")

    @staticmethod
    def _require_shot(project: JsonObject, shot_id: str) -> JsonObject:
        shot = next(
            (item for item in project.get("script", {}).get("shots", []) if item["id"] == shot_id),
            None,
        )
        if shot is None:
            raise DomainError("SHOT_NOT_FOUND")
        return dict(shot)

    @staticmethod
    def _get_scene_by_id(script: JsonObject, scene_id: str) -> JsonObject | None:
        """Get a scene by its ID from the script."""
        scenes = script.get("scenes", [])
        for scene in scenes:
            if isinstance(scene, dict) and scene.get("id") == scene_id:
                return scene
        return None

    @staticmethod
    def _validate_script(script: object) -> list[JsonObject]:
        return StoryScripts._validate_script(script)
