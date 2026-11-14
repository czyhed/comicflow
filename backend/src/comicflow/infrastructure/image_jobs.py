"""Character image journal: unique operations, leases and transactional installation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject
from comicflow.infrastructure.database import CharacterRow, ImageJobRow, OutboxRow, ProjectStateRow
from comicflow.production.character_boards import approve_board
from comicflow.production.reference_images import invalidate_reference_board

TERMINAL = {"succeeded", "failed", "cancelled"}
Change = Callable[[JsonObject], None]


def inputs(character: JsonObject) -> JsonObject:
    return {
        key: deepcopy(character.get(key))
        for key in (
            "id",
            "projectId",
            "revision",
            "name",
            "appearance",
            "clothing",
            "referenceImagePrompt",
            "referenceImageVersion",
            "referenceImageObjectKey",
        )
    } | (
        {"referenceImageUrl": character.get("referenceImageUrl")}
        if not character.get("referenceImageObjectKey")
        else {}
    )


def matches(job: JsonObject, character: JsonObject, project: JsonObject) -> bool:
    return inputs(character) == job["characterInput"] and project.get(
        "visualStyleProfile"
    ) == job.get("styleSnapshot")


def active_slot(job: JsonObject) -> str | None:
    return None if job["status"] in TERMINAL else str(job["slot"])


def existing(old: JsonObject, new: JsonObject) -> JsonObject:
    if old["operationKey"] != new["operationKey"] and old["fingerprint"] != new["fingerprint"]:
        raise DomainError("IMAGE_JOB_ACTIVE", {"jobId": old["id"]})
    return deepcopy(old)


def event(job: JsonObject, status: str) -> None:
    job.update(status=status, updatedAt=datetime.now(UTC).isoformat())
    job.setdefault("history", []).append({"status": status, "at": job["updatedAt"]})


def owns(job: JsonObject, token: str) -> None:
    if job.get("leaseToken") != token or job.get("leaseUntil", 0) <= time.time():
        raise DomainError("IMAGE_JOB_LEASE_LOST")


def install(
    job: JsonObject,
    character: JsonObject,
    project: JsonObject,
    key: str,
    asset: JsonObject,
    final: bool,
) -> bool:
    applied = matches(job, character, project)
    job.setdefault("results", {})[key] = deepcopy(asset)
    if applied:
        if key == "candidate":
            character.update(
                referenceImageCandidate=deepcopy(asset), referenceImageStatus="candidate"
            )
        elif key == "board-candidate":
            character["referenceBoardCandidate"] = deepcopy(asset)
        elif key == "board":
            character["referenceBoard"] = deepcopy(asset)
        else:
            views = [v for v in character.get("referenceViews", []) if v.get("view") != key]
            views.append(deepcopy(asset))
            character["referenceViews"] = views
            character["referenceImageStatus"] = (
                "views-ready" if len(views) == 3 else "views-partial"
            )
            invalidate_reference_board(character)
        project["version"] += 1
    job["applied"] = applied
    job.update(taskId=None, providerAsset=None, currentStep=None)
    if final or not applied:
        event(job, "succeeded")
        job.update(
            leaseToken=None, leaseUntil=0, error=None if applied else "IMAGE_JOB_INPUT_CHANGED"
        )
    else:
        event(job, "preparing")
        job["leaseUntil"] = time.time() + job["leaseSeconds"]
    job["result"] = {
        "character": deepcopy(character),
        "projectVersion": project["version"],
        "applied": applied,
        "reused": not job.get("callsStarted"),
    }
    if job["purpose"] == "candidate":
        job["result"]["candidate"] = deepcopy(job["results"].get("candidate"))
    elif job["purpose"] in {"board", "text-board"}:
        job["result"]["candidate"] = deepcopy(job["results"].get("board-candidate"))
    else:
        job["result"]["views"] = deepcopy(character.get("referenceViews", []))
    return applied


class ImageJobStore:
    async def get(self, job_id: str) -> JsonObject | None:
        raise NotImplementedError

    async def list(self, project_id: str) -> list[JsonObject]:
        raise NotImplementedError

    async def operation(self, project_id: str, key: str) -> JsonObject | None:
        return next((j for j in await self.list(project_id) if j["operationKey"] == key), None)

    async def create(self, job: JsonObject) -> JsonObject:
        raise NotImplementedError

    async def change(self, job_id: str, change: Change) -> JsonObject:
        raise NotImplementedError

    async def install(
        self, job_id: str, token: str, key: str, asset: JsonObject, *, final: bool = False
    ) -> JsonObject:
        raise NotImplementedError

    async def approve_board(self, project_id: str, character_id: str, candidate_id: str,
                            expected_version: int) -> JsonObject:
        raise NotImplementedError


    async def claim(self, job_id: str, token: str) -> JsonObject | None:
        def claim(job: JsonObject) -> None:
            if (
                job["status"] in TERMINAL | {"unknown", "recoverable"}
                or job.get("leaseUntil", 0) > time.time()
            ):
                return
            if job["status"] == "submitting" and not job.get("taskId"):
                event(job, "unknown")
                job.update(error="IMAGE_SUBMISSION_UNKNOWN", leaseToken=None, leaseUntil=0)
                return
            job.update(
                leaseToken=token,
                leaseUntil=time.time() + job["leaseSeconds"],
                attempts=job.get("attempts", 0) + 1,
            )

        job = await self.change(job_id, claim)
        return job if job.get("leaseToken") == token else None

    async def checkpoint(
        self, job_id: str, token: str, status: str, fields: JsonObject | None = None
    ) -> JsonObject:
        def write(job: JsonObject) -> None:
            owns(job, token)
            event(job, status)
            job.update(deepcopy(fields or {}))
            job["leaseUntil"] = time.time() + job["leaseSeconds"]
            if status == "submitting":
                job["callsStarted"] += 1
            if status in TERMINAL | {"unknown", "recoverable"}:
                job.update(leaseToken=None, leaseUntil=0)

        return await self.change(job_id, write)

    async def recover(self, job_id: str) -> JsonObject:
        def recover(job: JsonObject) -> None:
            if job["status"] in TERMINAL:
                raise DomainError("IMAGE_JOB_NOT_RECOVERABLE")
            if job.get("leaseUntil", 0) > time.time():
                raise DomainError("IMAGE_JOB_BUSY")
            if job.get("providerAsset"):
                event(job, "finalizing")
            elif job.get("taskId"):
                event(job, "polling")
            elif job["status"] in {"unknown", "submitting"}:
                raise DomainError("IMAGE_SUBMISSION_UNKNOWN")
            else:
                event(job, "preparing")
            job.update(error=None, leaseToken=None, leaseUntil=0, _enqueue=True)

        return await self.change(job_id, recover)


class MemoryImageJobStore(ImageJobStore):
    def __init__(self, projects: Any, characters: Any) -> None:
        self.projects, self.characters = projects, characters
        self.jobs: dict[str, JsonObject] = {}
        self.lock = asyncio.Lock()

    async def get(self, job_id: str) -> JsonObject | None:
        return deepcopy(self.jobs.get(job_id))

    async def list(self, project_id: str) -> list[JsonObject]:
        return [deepcopy(j) for j in self.jobs.values() if j["projectId"] == project_id]

    async def create(self, job: JsonObject) -> JsonObject:
        async with self.lock:
            old = next(
                (j for j in self.jobs.values() if j["operationKey"] == job["operationKey"]), None
            )
            old = old or next(
                (j for j in self.jobs.values() if active_slot(j) == active_slot(job)), None
            )
            if old:
                return existing(old, job)
            self.jobs[job["id"]] = deepcopy(job)
            return deepcopy(job)

    async def change(self, job_id: str, change: Change) -> JsonObject:
        async with self.lock:
            if job_id not in self.jobs:
                raise DomainError("IMAGE_JOB_NOT_FOUND")
            job = deepcopy(self.jobs[job_id])
            change(job)
            job.pop("_enqueue", None)
            self.jobs[job_id] = deepcopy(job)
            return job

    async def install(
        self, job_id: str, token: str, key: str, asset: JsonObject, *, final: bool = False
    ) -> JsonObject:
        async with self.lock:
            job = deepcopy(self.jobs[job_id])
            owns(job, token)
            record = await self.projects.get(job["projectId"])
            character = await self.characters.get(job["characterId"])
            if record is None:
                raise DomainError("PROJECT_NOT_FOUND")
            if install(job, character or {}, record.project, key, asset, final):
                await self.characters.save(character)
                await self.projects.save(record)
            self.jobs[job_id] = deepcopy(job)
            return job

    async def approve_board(self, project_id: str, character_id: str, candidate_id: str,
                            expected_version: int) -> JsonObject:
        async with self.lock:
            record = await self.projects.get(project_id)
            character = await self.characters.get(character_id)
            if record is None:
                raise DomainError('PROJECT_NOT_FOUND')
            if not character or character.get('projectId') != project_id:
                raise DomainError('CHARACTER_ACCESS_DENIED')
            if approve_board(character, record.project, candidate_id, expected_version):
                await self.characters.save(character)
                await self.projects.save(record)
            return {'character': deepcopy(character), 'projectVersion': record.project['version']}


class SqlImageJobStore(ImageJobStore):
    def __init__(self, sessions: Any) -> None:
        self.sessions = sessions

    @staticmethod
    def enqueue(session: Any, job: JsonObject) -> None:
        session.add(
            OutboxRow(
                id=f"evt_{uuid4().hex}",
                topic="production.image.queued",
                payload={"jobId": job["id"]},
                status="pending",
                created_at=datetime.now(UTC),
            )
        )

    async def get(self, job_id: str) -> JsonObject | None:
        async with self.sessions() as session:
            row = await session.get(ImageJobRow, job_id)
            return deepcopy(row.payload) if row else None

    async def list(self, project_id: str) -> list[JsonObject]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ImageJobRow).where(ImageJobRow.project_id == project_id)
            )
            return [deepcopy(r.payload) for r in rows]

    async def create(self, job: JsonObject) -> JsonObject:
        try:
            async with self.sessions.begin() as session:
                session.add(
                    ImageJobRow(
                        id=job["id"],
                        project_id=job["projectId"],
                        operation_key=job["operationKey"],
                        active_slot=active_slot(job),
                        revision=0,
                        payload=deepcopy(job),
                    )
                )
                self.enqueue(session, job)
            return deepcopy(job)
        except IntegrityError:
            async with self.sessions() as session:
                row = await session.scalar(
                    select(ImageJobRow).where(ImageJobRow.operation_key == job["operationKey"])
                )
                if row is None:
                    row = await session.scalar(
                        select(ImageJobRow).where(ImageJobRow.active_slot == active_slot(job))
                    )
                if row is None:
                    raise DomainError("IMAGE_JOB_CONFLICT") from None
                return existing(row.payload, job)

    async def change(self, job_id: str, change: Change) -> JsonObject:
        for _ in range(8):
            async with self.sessions.begin() as session:
                row = await session.get(ImageJobRow, job_id)
                if row is None:
                    raise DomainError("IMAGE_JOB_NOT_FOUND")
                job: JsonObject = deepcopy(row.payload)
                change(job)
                enqueue = job.pop("_enqueue", False)
                result = await session.execute(
                    update(ImageJobRow)
                    .where(ImageJobRow.id == job_id, ImageJobRow.revision == row.revision)
                    .values(payload=job, revision=row.revision + 1, active_slot=active_slot(job))
                )
                if result.rowcount != 1:
                    continue
                if enqueue:
                    self.enqueue(session, job)
                return job
        raise DomainError("IMAGE_JOB_CONFLICT")

    async def install(
        self, job_id: str, token: str, key: str, asset: JsonObject, *, final: bool = False
    ) -> JsonObject:
        async with self.sessions.begin() as session:
            row = await session.get(ImageJobRow, job_id, with_for_update=True)
            if row is None:
                raise DomainError("IMAGE_JOB_NOT_FOUND")
            job: JsonObject = deepcopy(row.payload)
            owns(job, token)
            project_row = await session.get(ProjectStateRow, job["projectId"], with_for_update=True)
            character_row = await session.get(
                CharacterRow, job["characterId"], with_for_update=True
            )
            if project_row is None:
                raise DomainError("PROJECT_NOT_FOUND")
            payload = deepcopy(project_row.payload)
            character = deepcopy(character_row.payload) if character_row else {}
            if install(job, character, payload["project"], key, asset, final):
                assert character_row is not None
                result = await session.execute(
                    update(CharacterRow)
                    .where(
                        CharacterRow.id == character_row.id,
                        CharacterRow.updated_at == character_row.updated_at,
                    )
                    .values(payload=character, updated_at=datetime.now(UTC))
                )
                if result.rowcount != 1:
                    raise DomainError("IMAGE_JOB_CONFLICT")
                result = await session.execute(
                    update(ProjectStateRow)
                    .where(
                        ProjectStateRow.id == project_row.id,
                        ProjectStateRow.updated_at == project_row.updated_at,
                    )
                    .values(payload=payload, updated_at=datetime.now(UTC))
                )
                if result.rowcount != 1:
                    raise DomainError("IMAGE_JOB_CONFLICT")
            result = await session.execute(
                update(ImageJobRow)
                .where(ImageJobRow.id == job_id, ImageJobRow.revision == row.revision)
                .values(payload=job, revision=row.revision + 1, active_slot=active_slot(job))
            )
            if result.rowcount != 1:
                raise DomainError("IMAGE_JOB_LEASE_LOST")
            return job

    async def approve_board(self, project_id: str, character_id: str, candidate_id: str,
                            expected_version: int) -> JsonObject:
        async with self.sessions.begin() as session:
            project_row = await session.get(ProjectStateRow, project_id, with_for_update=True)
            character_row = await session.get(CharacterRow, character_id, with_for_update=True)
            if project_row is None:
                raise DomainError('PROJECT_NOT_FOUND')
            character = deepcopy(character_row.payload) if character_row else {}
            if character.get('projectId') != project_id:
                raise DomainError('CHARACTER_ACCESS_DENIED')
            payload = deepcopy(project_row.payload)
            if approve_board(character, payload['project'], candidate_id, expected_version):
                assert character_row is not None
                for table, row, value in ((CharacterRow, character_row, character),
                                          (ProjectStateRow, project_row, payload)):
                    result = await session.execute(update(table).where(
                        table.id == row.id, table.updated_at == row.updated_at,
                    ).values(payload=value, updated_at=datetime.now(UTC)))
                    if result.rowcount != 1:
                        raise DomainError('VERSION_CONFLICT')
            return {'character': character, 'projectVersion': payload['project']['version']}
