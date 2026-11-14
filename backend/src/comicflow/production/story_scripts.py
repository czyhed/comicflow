from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

from comicflow.domain.errors import DomainError
from comicflow.domain.models import Actor, JsonObject, ProjectRecord
from comicflow.production.interfaces import (
    CharacterRepository,
    ModerationProvider,
    ProjectRepository,
    TextProvider,
)
from comicflow.production.script_assets import invalidate_edited_script_assets
from comicflow.production.script_characters import bind_script_characters
from comicflow.production.script_preview import normalize_preview
from comicflow.production.visual_styles import (
    styled_script_input,
)
from comicflow.providers.drama_skills import (
    apply_continuity_plan,
)
from comicflow.providers.error_mapping import map_provider_error
from comicflow.providers.message_contract import (
    normalize_guided_question_message,
    normalize_script_message,
    normalize_story_message,
    valid_speech_fields,
)
from comicflow.providers.text_errors import TextRequestError
from comicflow.providers.text_progress import report_text_progress


class StoryScripts:
    """Story/script operations; production advancement stays with the caller."""

    def __init__(
        self, *, repository: ProjectRepository, characters: CharacterRepository,
        text_provider: TextProvider, moderation_provider: ModerationProvider | None,
        locks: dict[str, asyncio.Lock], model_config_revision: int,
        sync_generation_state: Callable[[JsonObject], Awaitable[None]],
        append_generation_event: Callable[[str, JsonObject], Awaitable[None]],
        create_character: Callable[..., Awaitable[JsonObject]],
    ) -> None:
        self._repository = repository
        self._character_repository = characters
        self._text_provider = text_provider
        self._moderation_provider = moderation_provider
        self._generation_locks = locks
        self._model_config_revision = model_config_revision
        self._sync_generation_state = sync_generation_state
        self._append_generation_event = append_generation_event
        self.create_character = create_character

    async def _generate_story_text_with_events(
        self, project: JsonObject, project_id: str
    ) -> str:
        stream_method = getattr(self._text_provider, "stream_story_text", None)
        if not callable(stream_method):
            result = await self._call_provider(
                self._text_provider.generate_story_text,
                project["input"]["story"],
                project_id,
                target_duration_sec=int(project["input"]["durationSec"]),
            )
            return str(result)
        chunks: list[str] = []
        async for chunk in stream_method(
            project["input"]["story"],
            project_id,
            target_duration_sec=int(project["input"]["durationSec"]),
        ):
            if not isinstance(chunk, str) or not chunk:
                continue
            current = "".join(chunks)
            # Some compatible providers send cumulative snapshots instead of deltas.
            # Convert those snapshots to a true delta and ignore duplicate frames.
            if not getattr(self._text_provider, 'story_stream_is_delta', False):
                if chunk == current or (current and chunk.startswith(current)):
                    chunk = chunk[len(current) :]
                elif current.endswith(chunk):
                    continue
            if not chunk:
                continue
            chunks.append(chunk)
            await report_text_progress({"type": "delta", "delta": chunk})
            project["generationPartialText"] = "".join(chunks)
            await self._sync_generation_state(project)
            await self._append_generation_event(
                project_id,
                {
                    "type": "generation_delta",
                    "mode": "automatic",
                    "task": "story_expansion",
                    "delta": chunk,
                },
            )
        streamed = "".join(chunks)
        await report_text_progress({'type': 'phase', 'phase': 'validating'})
        if streamed.lstrip().startswith("{"):
            normalized = normalize_story_message(
                streamed, target_duration_sec=int(project["input"]["durationSec"]),
            )
            return str(normalized["text"])
        return streamed

    async def generate_story_text(
        self, project_id: str, *, idempotency_key: str | None = None
    ) -> JsonObject:
        lock = self._generation_locks.setdefault(project_id, asyncio.Lock())
        if lock.locked():
            raise DomainError("GENERATION_IN_PROGRESS")
        async with lock:
            return await self._generate_story_text(project_id, idempotency_key=idempotency_key)

    async def _generate_story_text(
        self, project_id: str, *, idempotency_key: str | None = None
    ) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        if project.get("input", {}).get("mode") != "automatic":
            raise DomainError("WORKFLOW_MODE_MISMATCH")
        if (
            project.get("stage")
            in {"story-generated", "storyboard-ready", "script-completed", "exported"}
            and isinstance(project.get("generatedStoryText"), str)
            and project["generatedStoryText"].strip()
        ):
            return self._story_result(project)
        if idempotency_key and project.get("storyTextIdempotencyKey") == idempotency_key:
            return self._story_result(project)

        moderation = (
            await self._moderation_provider.moderate(project["input"]["story"])
            if self._moderation_provider is not None
            else {"status": "approved"}
        )
        if moderation.get("status") == "blocked":
            project["stage"] = "moderation-blocked"
            project["moderation"] = {
                "status": "blocked",
                "reasonCode": moderation.get("reasonCode", "UNSAFE_CONTENT"),
            }
            await self._repository.save(record)
            raise DomainError("MODERATION_BLOCKED")
        if moderation.get("status") == "review":
            project["stage"] = "moderation-review"
            project["moderation"] = moderation
            await self._repository.save(record)
            raise DomainError("MODERATION_REVIEW_REQUIRED")

        text_cost = 2
        balance = sum(event["amount"] for event in project["creditLedger"])
        if balance < text_cost:
            raise DomainError("INSUFFICIENT_CREDIT")
        project["creditLedger"].append({"type": "reservation", "amount": -text_cost})
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        session.update({"stage": "story-generating", "status": "running"})
        session["task"] = "story_expansion"
        project.pop('generationErrorDetail', None)
        project["stage"] = "story-generating"
        await self._repository.save(record)
        await self._sync_generation_state(project)
        await self._append_generation_event(
            project_id,
            {"type": "generation_started", "mode": "automatic", "task": "story_expansion"},
        )
        try:
            story_text = await self._generate_story_text_with_events(project, project_id)
            if not isinstance(story_text, str) or not story_text.strip() or len(story_text) > 8000:
                raise RuntimeError("PROVIDER_RESPONSE_INVALID")
            story_text = story_text.strip()
            story_text = self._expand_story_text(story_text, int(project["input"]["durationSec"]))
            project["generationPartialText"] = story_text
        except RuntimeError as error:
            code = self._map_provider_error(str(error))
            project["stage"] = "story-failed"
            project["generationError"] = code
            session.update({"stage": "story-failed", "status": "failed", "retryCount": 0})
            detail = deepcopy(error.detail) if isinstance(error, TextRequestError) else {}
            project['generationErrorDetail'] = detail
            project["creditLedger"].append(
                {"type": "release", "amount": text_cost, "reason": "provider-failed"}
            )
            await self._repository.save(record)
            await self._sync_generation_state(project)
            await self._append_generation_event(
                project_id,
                {
                    "type": "generation_failed",
                    "mode": "automatic",
                    "task": "story_expansion",
                    "error": code,
                    "detail": detail,
                },
            )
            raise DomainError(code, detail) from error
        project["moderation"] = moderation
        project["generatedStoryText"] = story_text
        project["storyTextVersion"] = int(project.get("version", 1)) + 1
        project["version"] = project["storyTextVersion"]
        project["stage"] = "story-generated"
        project["creditLedger"].append({"type": "settlement", "amount": 0, "consumed": text_cost})
        project["storyTextIdempotencyKey"] = idempotency_key
        session.update({"stage": "story-generated", "status": "ready", "retryCount": 0})
        await self._repository.save(record)
        await self._sync_generation_state(project)
        await self._append_generation_event(
            project_id,
            {
                "type": "generation_completed",
                "mode": "automatic",
                "task": "story_expansion",
                "text": story_text,
            },
        )
        return self._story_result(project)

    async def update_story_text(
        self, project_id: str, story_text: str, *, expected_version: int
    ) -> JsonObject:
        normalized = story_text.strip()
        if not normalized or len(normalized) > 8000:
            raise DomainError("STORY_TEXT_INVALID")
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        project["generatedStoryText"] = normalized
        project["storyTextVersion"] = int(project.get("storyTextVersion", 0)) + 1
        project["version"] += 1
        project["script"] = None
        project["stage"] = "story-generated"
        project.pop("generationError", None)
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        session.update({"stage": "story-generated", "status": "ready"})
        await self._repository.save(record)
        await self._sync_generation_state(project)
        return self._story_result(project)

    async def split_script(self, project_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        story_text = project.get("generatedStoryText")
        if not isinstance(story_text, str) or not story_text.strip():
            raise DomainError("STORY_TEXT_REQUIRED")
        try:
            raw_script = await self._call_provider(
                self._text_provider.split_script,
                styled_script_input(project, story_text),
                project_id,
                target_duration_sec=int(project["input"]["durationSec"]),
            )
            if not isinstance(raw_script, dict) or raw_script.get("kind") != "script":
                raise RuntimeError("PROVIDER_INVALID_RESPONSE")

            # First pass: normalize without character mapping to extract character names
            temp_script = normalize_script_message(
                raw_script, target_duration_sec=int(project["input"]["durationSec"])
            )

            # Extract unique character names from all shots
            character_names: set[str] = set()
            for shot in temp_script.get("shots", []):
                if isinstance(shot, dict):
                    for name in shot.get("characters", []):
                        if isinstance(name, str) and name.strip():
                            character_names.add(name.strip())

            # Create character cards for each unique character name
            character_map: dict[str, str] = {}
            guest_actor = Actor.guest(record.guest_session["id"])
            for char_name in character_names:
                character = await self.create_character(
                    {
                        "name": char_name,
                        "appearance": "待定",
                        "clothing": "待定",
                        "personality": "待定",
                        "voice": {
                            "provider": "yun-free",
                            "voiceId": "female-tianmei",
                            "language": "zh-CN",
                        },
                    },
                    actor=guest_actor,
                    project_id=project_id,
                )
                character_map[char_name] = character["id"]

            # Second pass: re-normalize with character mapping to fill characterIds
            script = normalize_script_message(
                raw_script,
                target_duration_sec=int(project["input"]["durationSec"]),
                character_map=character_map if character_map else None,
            )
            script = apply_continuity_plan(script)
        except RuntimeError as error:
            detail = deepcopy(error.detail) if isinstance(error, TextRequestError) else {}
            raise DomainError(self._map_provider_error(str(error)), detail) from error
        if not isinstance(script, dict) or not script.get("title"):
            raise DomainError("PROVIDER_INVALID_RESPONSE")
        project["script"] = deepcopy(script)
        project["version"] += 1
        project["stage"] = (
            "awaiting-confirmation"
            if project.get("input", {}).get("mode") == "guided"
            else "script-completed"
        )
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        session.update({"stage": project["stage"], "status": "ready"})
        await self._repository.save(record)
        await self._sync_generation_state(project)
        return self._script_result(project)

    async def preview_script(self, project_id: str) -> JsonObject:
        """Generate a normalized script preview without changing project state."""
        from comicflow.providers.text_progress import report_text_progress

        record = await self._require_record(project_id)
        project = deepcopy(record.project)
        story_text = project.get("generatedStoryText")
        if not isinstance(story_text, str) or not story_text.strip():
            raise DomainError("STORY_TEXT_REQUIRED")

        # Phase 1: Quality preflight
        await report_text_progress({
            'type': 'phase', 'phase': 'quality-check', 'label': '检查故事质量'
        })

        try:
            # Phase 2: Generate script
            await report_text_progress({
                'type': 'phase', 'phase': 'generating-script', 'label': '正在生成剧本'
            })
            script = await self._call_provider(
                self._text_provider.split_script,
                styled_script_input(project, story_text),
                project_id,
                target_duration_sec=int(project["input"]["durationSec"]),
            )
            if isinstance(script, dict) and script.get("kind") == "script":
                script = normalize_script_message(
                    script, target_duration_sec=int(project["input"]["durationSec"])
                )
        except RuntimeError as error:
            detail = deepcopy(error.detail) if isinstance(error, TextRequestError) else {}
            raise DomainError(self._map_provider_error(str(error)), detail) from error
        if not isinstance(script, dict) or not script.get("title"):
            raise DomainError("PROVIDER_INVALID_RESPONSE")

        # Phase 3: Apply continuity
        await report_text_progress({
            'type': 'phase', 'phase': 'continuity', 'label': '应用延续性规则'
        })
        try:
            script = normalize_preview(
                script, target_duration_sec=int(project['input']['durationSec'])
            )
            script = apply_continuity_plan(script)
        except RuntimeError as error:
            raise DomainError('PROVIDER_INVALID_RESPONSE') from error

        # Phase 4: Bind characters
        await report_text_progress({
            'type': 'phase', 'phase': 'binding-characters', 'label': '绑定角色信息'
        })
        script, _ = bind_script_characters(
            record, script, await self._character_repository.list()
        )
        scenes = script.get("scenes", [])
        shots = script.get("shots", [])
        shot_by_id = {str(shot.get("id")): shot for shot in shots if isinstance(shot, dict)}
        scene_details = [
            {
                "id": scene.get("id"),
                "title": scene.get("title"),
                "shots": [
                    {
                        "id": shot_id,
                        "title": shot_by_id.get(str(shot_id), {}).get("title", "未识别镜头"),
                        "dialogue": shot_by_id.get(str(shot_id), {}).get("dialogue", ""),
                        "visualDescription": shot_by_id.get(str(shot_id), {}).get(
                            "visualDescription", ""
                        ),
                    }
                    for shot_id in scene.get("shotIds", [])
                ],
            }
            for scene in scenes
            if isinstance(scene, dict)
        ]
        dialogue = sum(
            1
            for shot in shots
            if isinstance(shot, dict) and str(shot.get("dialogue", "")).strip()
        )
        return {
            "script": deepcopy(script),
            "expectedVersion": project['version'],
            "summary": {
                "scenes": len(scenes) if isinstance(scenes, list) else 0,
                "shots": len(shots) if isinstance(shots, list) else 0,
                "dialogue": dialogue,
                "narration": sum(
                    1
                    for shot in shots
                    if isinstance(shot, dict) and str(shot.get("narration", "")).strip()
                ),
                "issues": [],
            },
            "sceneDetails": scene_details,
        }

    async def commit_script_preview(
        self, project_id: str, script: JsonObject, *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        try:
            normalize_preview(
                script, target_duration_sec=int(record.project['input']['durationSec'])
            )
        except RuntimeError as error:
            raise DomainError('SCRIPT_INVALID') from error
        script, pending_characters = bind_script_characters(
            record, script, await self._character_repository.list()
        )
        project = record.project
        if project.get('script'):
            project.setdefault('scriptVersions', []).append({
                'version': project['version'], 'projectId': project_id,
                'script': deepcopy(project['script']),
            })
        if project.pop('scriptConfirmedVersion', None) is not None:
            project['downstreamInvalidated'] = True
        project['script'] = deepcopy(script)
        project['version'] += 1
        project['stage'] = 'awaiting-confirmation'
        project['validationErrors'] = []
        session = project.setdefault('generationSession', {})
        session.update({'stage': 'awaiting-confirmation', 'status': 'ready'})
        for character in pending_characters:
            await self._character_repository.save(character)
        await self._repository.save(record)
        await self._sync_generation_state(project)
        return self._script_result(project)

    async def generate_script(
        self, project_id: str, *, idempotency_key: str | None = None
    ) -> JsonObject:
        lock = self._generation_locks.setdefault(project_id, asyncio.Lock())
        if lock.locked():
            raise DomainError("GENERATION_IN_PROGRESS")
        async with lock:
            return await self._generate_script(project_id, idempotency_key=idempotency_key)

    async def _generate_script(
        self, project_id: str, *, idempotency_key: str | None = None
    ) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        if project.get("input", {}).get("mode") != "guided":
            raise DomainError("WORKFLOW_MODE_MISMATCH")
        if (
            project.get("stage")
            in {"awaiting-confirmation", "script-completed", "storyboard-ready", "exported"}
            and isinstance(project.get("script"), dict)
            and project["script"].get("title")
        ):
            return self._script_result(project)
        if idempotency_key and project.get("scriptIdempotencyKey") == idempotency_key:
            return self._script_result(project)

        moderation = (
            await self._moderation_provider.moderate(project["input"]["story"])
            if self._moderation_provider is not None
            else {"status": "approved"}
        )
        if moderation.get("status") == "blocked":
            project["stage"] = "moderation-blocked"
            project["moderation"] = {
                "status": "blocked",
                "reasonCode": moderation.get("reasonCode", "UNSAFE_CONTENT"),
            }
            await self._repository.save(record)
            raise DomainError("MODERATION_BLOCKED")
        if moderation.get("status") == "review":
            project["stage"] = "moderation-review"
            project["moderation"] = moderation
            await self._repository.save(record)
            raise DomainError("MODERATION_REVIEW_REQUIRED")

        script_cost = 4
        balance = sum(event["amount"] for event in project["creditLedger"])
        if balance < script_cost:
            raise DomainError("INSUFFICIENT_CREDIT")

        project["creditLedger"].append({"type": "reservation", "amount": -script_cost})
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        session.update({"stage": "script-generating", "status": "running"})
        session["task"] = "script_outline"
        project["stage"] = "script-generating"
        await self._repository.save(record)
        await self._sync_generation_state(project)
        try:
            raw_script = await self._call_provider(
                self._text_provider.generate_script,
                styled_script_input(project, project["input"]["story"]),
                project_id,
                target_duration_sec=int(project["input"]["durationSec"]),
            )
            if not isinstance(raw_script, dict) or raw_script.get("kind") != "script":
                raise RuntimeError("PROVIDER_INVALID_RESPONSE")

            # First pass: normalize without character mapping to extract character names
            temp_script = normalize_script_message(
                raw_script, target_duration_sec=int(project["input"]["durationSec"])
            )

            # Extract unique character names from all shots
            character_names: set[str] = set()
            for shot in temp_script.get("shots", []):
                if isinstance(shot, dict):
                    for name in shot.get("characters", []):
                        if isinstance(name, str) and name.strip():
                            character_names.add(name.strip())

            # Create character cards for each unique character name
            character_map: dict[str, str] = {}
            guest_actor = Actor.guest(record.guest_session["id"])
            for char_name in character_names:
                # Create a basic character card with the name
                character = await self.create_character(
                    {
                        "name": char_name,
                        "appearance": "待定",
                        "clothing": "待定",
                        "personality": "待定",
                        "voice": {
                            "provider": "yun-free",
                            "voiceId": "female-tianmei",
                            "language": "zh-CN",
                        },
                    },
                    actor=guest_actor,
                    project_id=project_id,
                )
                character_map[char_name] = character["id"]

            # Second pass: re-normalize with character mapping to fill characterIds
            script = normalize_script_message(
                raw_script,
                target_duration_sec=int(project["input"]["durationSec"]),
                character_map=character_map if character_map else None,
            )
            script = apply_continuity_plan(script)
        except RuntimeError as error:
            mapped = map_provider_error(str(error))
            project["stage"] = "script-failed"
            project["generationError"] = mapped
            project["creditLedger"].append(
                {"type": "release", "amount": script_cost, "reason": "provider-failed"}
            )
            await self._repository.save(record)
            await self._sync_generation_state(project)
            raise DomainError(mapped) from error
        project["moderation"] = moderation
        project["script"] = script
        project["stage"] = (
            "awaiting-confirmation" if project["input"]["mode"] == "guided" else "script-completed"
        )
        session.update({"stage": project["stage"], "status": "ready", "retryCount": 0})
        project["creditLedger"].append({"type": "settlement", "amount": 0, "consumed": script_cost})
        project["scriptIdempotencyKey"] = idempotency_key
        await self._repository.save(
            record,
            outbox_event=(
                {
                    "topic": "production.generation.advance",
                    "payload": {
                        "projectId": project_id,
                        "sessionId": session.get("id"),
                        "modelConfigRevision": self._model_config_revision,
                    },
                }
                if project["input"]["mode"] == "automatic"
                else None
            ),
        )
        await self._sync_generation_state(project)
        return self._script_result(project)

    async def sync_project_characters(
        self, project_id: str, *, expected_version: int
    ) -> JsonObject:
        """Recover saved model-extracted names without regenerating text or images."""
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        if not record.project.get('script'):
            raise DomainError('SCRIPT_REQUIRED')
        script, pending = bind_script_characters(
            record, record.project['script'], await self._character_repository.list()
        )
        if script != record.project['script']:
            record.project.setdefault('scriptVersions', []).append({
                'version': record.project['version'], 'projectId': project_id,
                'script': deepcopy(record.project['script']),
            })
            record.project['script'] = script
            record.project['version'] += 1
            if record.project.pop('scriptConfirmedVersion', None) is not None:
                record.project['downstreamInvalidated'] = True
                record.project['stage'] = 'awaiting-confirmation'
        for card in pending:
            await self._character_repository.save(card)
        await self._repository.save(record)
        return self._script_result(record.project)

    async def ask_guided_question(self, project_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        script = project.get("script")
        if not isinstance(script, dict):
            raise DomainError("SCRIPT_REQUIRED")
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        session["task"] = "guided_question"
        guided = cast(JsonObject, session.setdefault("guided", {}))
        transcript = guided.setdefault("transcript", [])
        question_count = int(guided.get("questionCount", len(transcript)))
        max_questions = int(guided.get("maxQuestions", 9))
        if question_count >= max_questions or guided.get("done"):
            guided.update({"questionCount": question_count, "done": True, "currentQuestion": ""})
            await self._repository.save(record)
            await self._sync_generation_state(project)
            return deepcopy(session)
        try:
            result = await self._call_provider(
                self._text_provider.generate_guided_question,
                str(project["input"]["story"]),
                script,
                transcript,
                project_id,
                target_duration_sec=int(project["input"]["durationSec"]),
            )
        except RuntimeError as error:
            raise DomainError(self._map_provider_error(str(error))) from error
        if isinstance(result, dict) and result.get("kind") == "guided_question":
            try:
                result = normalize_guided_question_message(result)
            except RuntimeError as error:
                raise DomainError("PROVIDER_INVALID_RESPONSE") from error
        question = result.get("question") if isinstance(result, dict) else None
        done = result.get("done") if isinstance(result, dict) else None
        if not isinstance(question, str) or not isinstance(done, bool):
            raise DomainError("PROVIDER_INVALID_RESPONSE")
        guided.update(
            {
                "currentQuestion": question[:80],
                "currentQuestionId": result.get("questionId", f"q-{question_count + 1}")
                if isinstance(result, dict)
                else f"q-{question_count + 1}",
                "currentQuestionType": result.get("questionType", "constraint")
                if isinstance(result, dict)
                else "constraint",
                "currentMissingFields": result.get("missingFields", [])
                if isinstance(result, dict)
                else [],
                "done": done,
            }
        )
        await self._repository.save(record)
        await self._sync_generation_state(project)
        return deepcopy(session)

    async def answer_guided_question(self, project_id: str, answer: str) -> JsonObject:
        normalized = answer.strip()
        if not normalized or len(normalized) > 400:
            raise DomainError("GUIDED_ANSWER_INVALID")
        record = await self._require_record(project_id)
        project = record.project
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        guided = cast(JsonObject, session.setdefault("guided", {}))
        question = str(guided.get("currentQuestion", ""))
        if guided.get("done") and not question:
            guided["questionCount"] = max(
                int(guided.get("questionCount", 0)), int(guided.get("maxQuestions", 9))
            )
            await self._repository.save(record)
            await self._sync_generation_state(project)
            return deepcopy(session)
        if not question:
            raise DomainError("SESSION_ACTION_INVALID")
        transcript = guided.setdefault("transcript", [])
        if not isinstance(transcript, list):
            raise DomainError("SESSION_ACTION_INVALID")
        context_length = sum(
            len(str(item.get("question", ""))) + len(str(item.get("answer", "")))
            for item in transcript
            if isinstance(item, dict)
        )
        if context_length + len(question) + len(normalized) > 1200:
            raise DomainError("GUIDED_CONTEXT_LIMIT")
        transcript.append(
            {
                "question": question,
                "answer": normalized,
                "questionId": guided.get("currentQuestionId", ""),
                "questionType": guided.get("currentQuestionType", "constraint"),
                "missingFields": guided.get("currentMissingFields", []),
            }
        )
        guided["questionCount"] = int(guided.get("questionCount", 0)) + 1
        guided["currentQuestion"] = ""
        guided["done"] = guided["questionCount"] >= int(guided.get("maxQuestions", 9))
        await self._repository.save(record)
        if not guided["done"]:
            return await self.ask_guided_question(project_id)
        await self._sync_generation_state(project)
        return deepcopy(session)

    async def skip_guided_question(self, project_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        guided = cast(JsonObject, session.setdefault("guided", {}))
        question = str(guided.get("currentQuestion", "")).strip()
        if not question or guided.get("done"):
            raise DomainError("SESSION_ACTION_INVALID")
        transcript = guided.setdefault("transcript", [])
        if not isinstance(transcript, list):
            raise DomainError("SESSION_ACTION_INVALID")
        question_type = str(guided.get("currentQuestionType", "constraint"))
        skipped = guided.setdefault("skippedTargets", [])
        if isinstance(skipped, list) and question_type not in skipped:
            skipped.append(question_type)
        transcript.append(
            {
                "question": question,
                "answer": "",
                "skipped": True,
                "questionId": guided.get("currentQuestionId", ""),
                "questionType": question_type,
                "missingFields": guided.get("currentMissingFields", []),
            }
        )
        guided["questionCount"] = int(guided.get("questionCount", 0)) + 1
        guided["currentQuestion"] = ""
        guided["done"] = guided["questionCount"] >= int(guided.get("maxQuestions", 9))
        await self._repository.save(record)
        if not guided["done"]:
            return await self.ask_guided_question(project_id)
        await self._sync_generation_state(project)
        return deepcopy(session)

    async def generate_detailed_script(self, project_id: str) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        script = project.get("script")
        if not isinstance(script, dict):
            raise DomainError("SCRIPT_REQUIRED")
        session = cast(JsonObject, project.setdefault("generationSession", {}))
        guided = cast(JsonObject, session.setdefault("guided", {}))
        session["task"] = "script_detail"
        transcript = guided.get("transcript", [])
        try:
            detailed = await self._call_provider(
                self._text_provider.generate_detailed_script,
                str(project["input"]["story"]),
                script,
                transcript,
                project_id,
                target_duration_sec=int(project["input"]["durationSec"]),
            )
            if isinstance(detailed, dict) and detailed.get("kind") == "script":
                detailed = normalize_script_message(
                    detailed, target_duration_sec=int(project["input"]["durationSec"])
                )
            if isinstance(detailed, dict):
                detailed = apply_continuity_plan(detailed)
        except RuntimeError as error:
            raise DomainError(self._map_provider_error(str(error))) from error
        project["script"] = detailed
        project["version"] += 1
        project["stage"] = "awaiting-confirmation"
        guided.update({"done": True, "currentQuestion": "", "detailGenerated": True})
        await self._repository.save(record)
        await self._sync_generation_state(project)
        return self._script_result(project)

    @staticmethod
    def _map_provider_error(code: str) -> str:
        return map_provider_error(code)

    @staticmethod
    def _expand_story_text(text: str, target_duration_sec: int) -> str:
        minimum = 300 if target_duration_sec <= 30 else 600 if target_duration_sec <= 60 else 900
        if len(text) >= minimum:
            return text
        sections = (
            "\n\n【开端】主角在异常迹象出现后确认目标，环境中的细节不断提醒他事情并不简单。",
            "\n\n【发展】阻碍逐步逼近，主角必须在有限时间内寻找线索，并承担继续行动的现实代价。",
            "\n\n【转折】关键证据揭开了被隐藏的关系，主角发现真正的冲突来自最信任的人。",
            "\n\n【结尾】主角做出不可逆的选择，问题得到阶段性回应，同时留下下一段旅程的悬念。",
        )
        expanded = text
        index = 0
        while len(expanded) < minimum:
            expanded += sections[index % len(sections)]
            index += 1
        return expanded[:8000]

    @staticmethod
    async def _call_provider(method: Any, *args: object, target_duration_sec: int) -> object:
        parameters = inspect.signature(method).parameters
        if "target_duration_sec" in parameters:
            return await method(*args, target_duration_sec=target_duration_sec)
        return await method(*args)

    async def list_script_versions(self, project_id: str) -> list[JsonObject]:
        record = await self._require_record(project_id)
        return deepcopy(record.project.get("scriptVersions", []))

    async def update_script(
        self, project_id: str, script: JsonObject, *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        previous = deepcopy(project.get('script') or {})
        project["script"] = deepcopy(script)
        if previous != script:
            if previous:
                project.setdefault('scriptVersions', []).append({
                    'version': project['version'], 'projectId': project_id, 'script': previous,
                })
            project.pop('scriptConfirmedVersion', None)
            invalidate_edited_script_assets(project, previous)
        project["version"] += 1
        project["stage"] = "awaiting-confirmation"
        await self._repository.save(record)
        return self._script_result(project)

    async def confirm_script(self, project_id: str, *, expected_version: int) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        errors = self._validate_script(project.get("script"))
        if errors:
            project["validationErrors"] = errors
            await self._repository.save(record)
            raise DomainError("SCRIPT_INVALID")

        script = project.get("script")
        if not isinstance(script, dict):
            raise DomainError("SCRIPT_INVALID")

        # Character references are generated from the character workspace so the
        # user can review a candidate before it becomes an input to video.
        character_ids: set[str] = set()
        for shot in script.get("shots", []):
            if isinstance(shot, dict):
                for char_id in shot.get("characterIds", []):
                    if isinstance(char_id, str):
                        character_ids.add(char_id)

        # Recognized names are draft identities, not invented visual specifications.
        # Confirmation validates character cards; image generation is a separate action.
        incomplete = []
        for char_id in character_ids:
            character = await self._character_repository.get(char_id)
            if character is None:
                raise DomainError('CHARACTER_NOT_FOUND')
            if not character.get('appearance') or not character.get('clothing'):
                incomplete.append(character['name'])
        if incomplete:
            raise DomainError('CHARACTER_FIELDS_REQUIRED', {'characters': sorted(incomplete)})

        project["stage"] = "storyboard-ready"
        project["scriptConfirmedVersion"] = project["version"]
        project["validationErrors"] = []
        project.setdefault("scriptVersions", []).append(
            {
                "version": project["version"],
                "projectId": project_id,
                "script": deepcopy(project["script"]),
            }
        )
        session = project.setdefault("generationSession", {})
        session.update({"stage": "storyboard-ready", "status": "ready"})
        await self._repository.save(record)
        return self._script_result(project)

    async def add_shot(
        self, project_id: str, shot: JsonObject, *, expected_version: int
    ) -> JsonObject:
        required = (
            "title",
            "action",
            "emotion",
            "shotSize",
            "durationSec",
            "visualDescription",
        )
        duration = shot.get("durationSec")
        if (
            any(not shot.get(field) for field in required)
            or not valid_speech_fields(shot)
            or not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or duration <= 0
        ):
            raise DomainError("SHOT_FIELDS_REQUIRED")
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        script = record.project["script"]
        next_shot = {**deepcopy(shot), "id": f"{project_id}_shot_{uuid4().hex[:8]}"}
        script["shots"].append(next_shot)
        script["scenes"][0]["shotIds"].append(next_shot["id"])
        return await self.save_script_mutation(record)

    async def duplicate_shot(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        source = self._require_shot(record.project, shot_id)
        duplicate = deepcopy(source)
        duplicate["id"] = f"{project_id}_shot_{uuid4().hex[:8]}"
        shots = record.project["script"]["shots"]
        source_index = shots.index(source)
        shots.insert(source_index + 1, duplicate)
        for scene in record.project["script"]["scenes"]:
            if shot_id in scene["shotIds"]:
                index = scene["shotIds"].index(shot_id)
                scene["shotIds"].insert(index + 1, duplicate["id"])
                break
        return await self.save_script_mutation(record)

    async def delete_shot(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        self._require_shot(record.project, shot_id)
        script = record.project["script"]
        script["shots"] = [shot for shot in script["shots"] if shot["id"] != shot_id]
        for scene in script["scenes"]:
            scene["shotIds"] = [item for item in scene["shotIds"] if item != shot_id]
        return await self.save_script_mutation(record)

    async def reorder_shots(
        self, project_id: str, shot_ids: list[str], *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        script = record.project["script"]
        current = {shot["id"]: shot for shot in script["shots"]}
        if len(shot_ids) != len(current) or set(shot_ids) != set(current):
            raise DomainError("SHOT_ORDER_INVALID")
        script["shots"] = [current[shot_id] for shot_id in shot_ids]
        for scene in script["scenes"]:
            members = set(scene["shotIds"])
            scene["shotIds"] = [shot_id for shot_id in shot_ids if shot_id in members]
        return await self.save_script_mutation(record)

    async def _require_record(self, project_id: str) -> ProjectRecord:
        record = await self._repository.get(project_id)
        if record is None:
            raise DomainError("PROJECT_NOT_FOUND")
        return record

    async def save_script_mutation(self, record: ProjectRecord) -> JsonObject:
        project = record.project
        for index, shot in enumerate(project["script"]["shots"], start=1):
            shot["order"] = index
        project["version"] += 1
        project["stage"] = "awaiting-confirmation"
        project["downstreamInvalidated"] = True
        project.pop("validationErrors", None)
        await self._repository.save(record)
        return self._script_result(project)

    @staticmethod
    def _script_result(project: JsonObject) -> JsonObject:
        return {
            "project": deepcopy(project),
            "moderation": deepcopy(project.get("moderation")),
            "script": deepcopy(project.get("script")),
        }

    @staticmethod
    def _story_result(project: JsonObject) -> JsonObject:
        return {
            "project": deepcopy(project),
            "moderation": deepcopy(project.get("moderation")),
            "storyText": project.get("generatedStoryText"),
        }

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
    def _validate_script(script: object) -> list[JsonObject]:
        if not isinstance(script, dict):
            return [{"code": "SCRIPT_REQUIRED"}]
        shots = script.get("shots")
        scenes = script.get("scenes")
        if not script.get("title") or not isinstance(shots, list) or not isinstance(scenes, list):
            return [{"code": "SCRIPT_STRUCTURE_INVALID"}]
        errors: list[JsonObject] = []
        if not 6 <= len(shots) <= 12:
            errors.append({"code": "SHOT_COUNT_INVALID"})

        required = (
            "id",
            "action",
            "emotion",
            "shotSize",
            "durationSec",
            "visualDescription",
        )
        shot_ids: set[str] = set()
        total_duration = 0.0
        requires_scene_ids = any(isinstance(shot, dict) and "sceneId" in shot for shot in shots)
        for shot in shots:
            if not isinstance(shot, dict):
                errors.append({"code": "SHOT_INVALID"})
                continue
            shot_id = shot.get("id")
            duration = shot.get("durationSec")
            if (
                any(not shot.get(field) for field in required)
                or not valid_speech_fields(shot)
                or not isinstance(duration, (int, float))
                or isinstance(duration, bool)
                or duration <= 0
            ):
                errors.append({"code": "SHOT_FIELDS_REQUIRED", "shotId": shot_id})
                continue
            if not isinstance(shot_id, str):
                errors.append({"code": "SHOT_ID_INVALID"})
                continue
            if requires_scene_ids and not isinstance(shot.get("sceneId"), str):
                errors.append({"code": "SHOT_SCENE_ID_INVALID", "shotId": shot_id})
            if shot_id in shot_ids:
                errors.append({"code": "SHOT_ID_DUPLICATE", "shotId": shot_id})
            shot_ids.add(shot_id)
            total_duration += float(duration)

        referenced_ids: list[str] = []
        scene_context_required = any(
            isinstance(scene, dict)
            and any(
                key in scene
                for key in ("time", "location", "narrativeGoal", "conflict", "turningPoint")
            )
            for scene in scenes
        )
        for scene in scenes:
            if (
                not isinstance(scene, dict)
                or not scene.get("id")
                or not isinstance(scene.get("shotIds"), list)
            ):
                errors.append({"code": "SCENE_INVALID"})
                continue
            if scene_context_required and any(
                not isinstance(scene.get(field), str) or not scene[field].strip()
                for field in ("time", "location", "narrativeGoal", "conflict", "turningPoint")
            ):
                errors.append({"code": "SCENE_FIELDS_REQUIRED", "sceneId": scene.get("id")})
            referenced_ids.extend(scene["shotIds"])
        if set(referenced_ids) != shot_ids or len(referenced_ids) != len(shots):
            errors.append({"code": "SCENE_SHOT_REFERENCE_INVALID"})
        if not 30 <= total_duration <= 90:
            errors.append({"code": "SCRIPT_DURATION_INVALID"})
        return errors
