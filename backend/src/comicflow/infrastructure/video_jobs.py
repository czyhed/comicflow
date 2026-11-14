"""Durable video journal. CAS + unique active slot fence competing executors."""
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
from comicflow.infrastructure.database import OutboxRow, ProjectStateRow, VideoJobRow

TERMINAL = {'succeeded', 'failed', 'cancelled'}
Change = Callable[[JsonObject], None]


def slot(job: JsonObject) -> str | None:
    return None if job['status'] in TERMINAL else str(job['slot'])


def existing(job: JsonObject, proposed: JsonObject) -> JsonObject:
    if job['operationKey'] == proposed['operationKey']:
        return job  # Idempotent replay always refers to the original operation.
    if job['fingerprint'] != proposed['fingerprint']:
        raise DomainError('VIDEO_JOB_ACTIVE', {'jobId': job['id']})
    return job


def install(project: JsonObject, expected: JsonObject, asset: JsonObject) -> JsonObject:
    asset = deepcopy(asset)
    # Version alone is insufficient: image approvals need not bump project.version.
    adopt = project == expected and asset.get('valid', True)
    asset['valid'] = adopt
    if not adopt:
        asset.update(status='candidate')
        asset.setdefault('invalidatedReason', 'awaiting-adoption'
                         if project == expected else 'input-changed')
    assets = project.setdefault('visualAssets', [])
    if any(a.get('id') == asset['id'] for a in assets):
        return next(a for a in assets if a['id'] == asset['id'])
    if adopt:
        for old in assets:
            if old.get('shotId') == asset['shotId'] and old.get('valid'):
                old.update(valid=False, invalidatedReason='superseded')
        for old in project.get('audioAssets', []):
            if old.get('shotId') == asset['shotId'] and old.get('source') == 'video-native':
                old['valid'] = False
        project.get('timelines', {}).pop(asset['shotId'], None)
        project.update(exportManifest=None, downstreamInvalidated=True)
    assets.append(asset)
    return asset


def adopt_asset(project: JsonObject, asset_id: str) -> JsonObject:
    assets: list[JsonObject] = project.setdefault('visualAssets', [])
    candidate = next((item for item in assets if item.get('id') == asset_id), None)
    if candidate is None:
        raise DomainError('VIDEO_JOB_CANDIDATE_MISSING')
    if candidate.get('valid'):
        return candidate
    if candidate.get('status') != 'candidate':
        raise DomainError('VIDEO_JOB_NOT_ADOPTABLE')
    affected = {candidate['shotId']}
    for old in assets:
        if old.get('shotId') == candidate.get('shotId') and old.get('valid'):
            old.update(valid=False, invalidatedReason='superseded')
    # Only invalidate videos that consumed a changed tail, including their descendants.
    while True:
        dependents = [a for a in assets if a.get('valid') and
                      a.get('cascadeFromShotId') in affected and a is not candidate]
        if not dependents:
            break
        for old in dependents:
            old.update(valid=False, invalidatedReason='dependency-changed')
            affected.add(old['shotId'])
    for old in project.get('audioAssets', []):
        if old.get('shotId') in affected and old.get('source') == 'video-native':
            old['valid'] = False
    for old in project.get('lipSyncAssets', []):
        if old.get('shotId') in affected:
            old['valid'] = False
    for shot_id in affected:
        project.get('timelines', {}).pop(shot_id, None)
    project.update(exportManifest=None, downstreamInvalidated=True)
    candidate['valid'] = True
    candidate['status'] = 'current'
    candidate.pop('invalidatedReason', None)
    return candidate


def owns(job: JsonObject, token: str) -> None:
    if job.get('leaseToken') != token or job.get('leaseUntil', 0) <= time.time():
        raise DomainError('VIDEO_JOB_LEASE_LOST')


def event(job: JsonObject, status: str) -> None:
    job['status'] = status
    job['updatedAt'] = datetime.now(UTC).isoformat()
    job.setdefault('history', []).append({'status': status, 'at': job['updatedAt']})


class VideoJobStore:
    async def get(self, job_id: str) -> JsonObject | None:
        raise NotImplementedError

    async def list(self, project_id: str) -> list[JsonObject]:
        raise NotImplementedError

    async def operation(self, project_id: str, operation_key: str) -> JsonObject | None:
        return next((j for j in await self.list(project_id)
                     if j['operationKey'] == operation_key), None)

    async def create(self, job: JsonObject) -> JsonObject:
        raise NotImplementedError

    async def change(self, job_id: str, change: Change) -> JsonObject:
        raise NotImplementedError

    async def finish(self, job_id: str, token: str, expected: JsonObject,
                     asset: JsonObject) -> JsonObject:
        raise NotImplementedError

    async def adopt(self, project_id: str, job_id: str, expected: JsonObject) -> JsonObject:
        raise NotImplementedError

    async def claim(self, job_id: str, token: str) -> JsonObject | None:
        def claim(job: JsonObject) -> None:
            if job['status'] in TERMINAL | {'unknown', 'recoverable'}:
                return
            if job.get('leaseUntil', 0) > time.time():
                return
            if job['status'] in {'submitting', 'expanding'} and not job.get('taskId'):
                event(job, 'unknown')
                job.update(error='VIDEO_SUBMISSION_UNKNOWN', leaseToken=None, leaseUntil=0)
                return
            job.update(leaseToken=token, leaseUntil=time.time() + job['leaseSeconds'],
                       attempts=job.get('attempts', 0) + 1)
        job = await self.change(job_id, claim)
        return job if job.get('leaseToken') == token else None

    async def checkpoint(self, job_id: str, token: str, status: str,
                         fields: JsonObject | None = None) -> JsonObject:
        def write(job: JsonObject) -> None:
            owns(job, token)
            event(job, status)
            job.update(deepcopy(fields or {}))
            job['leaseUntil'] = time.time() + job['leaseSeconds']
            if status in {'expanding', 'submitting'}:
                kind = 'text' if status == 'expanding' else 'video'
                job['callsStarted'][kind] += 1
            if status in TERMINAL | {'unknown', 'recoverable'}:
                job.update(leaseToken=None, leaseUntil=0)
        return await self.change(job_id, write)

    async def recover(self, job_id: str, task_id: str | None = None) -> JsonObject:
        def recover(job: JsonObject) -> None:
            if job['status'] in TERMINAL:
                raise DomainError('VIDEO_JOB_NOT_RECOVERABLE')
            if job.get('leaseUntil', 0) > time.time():
                raise DomainError('VIDEO_JOB_BUSY')
            if task_id:
                if (job['status'] not in {'unknown', 'submitting'}
                        or job.get('taskId') or not job.get('compiled')):
                    raise DomainError('VIDEO_JOB_TASK_CONFLICT')
                job['taskId'] = task_id
            if job.get('taskId') or job.get('asset'):
                event(job, 'finalizing' if job.get('asset') else 'polling')
            elif job['status'] in {'unknown', 'submitting', 'expanding'}:
                raise DomainError('VIDEO_SUBMISSION_UNKNOWN')
            elif job['status'] == 'recoverable':
                event(job, job.get('resumeStage', 'preparing'))
            job.update(leaseToken=None, leaseUntil=0, error=None, errorDetail={})
            job['_enqueue'] = True
        return await self.change(job_id, recover)


class MemoryVideoJobStore(VideoJobStore):
    def __init__(self, projects: Any) -> None:
        self.projects = projects
        self.jobs: dict[str, JsonObject] = {}
        self.lock = asyncio.Lock()

    async def get(self, job_id: str) -> JsonObject | None:
        return deepcopy(self.jobs.get(job_id))

    async def list(self, project_id: str) -> list[JsonObject]:
        return [deepcopy(j) for j in self.jobs.values() if j['projectId'] == project_id]

    async def create(self, job: JsonObject) -> JsonObject:
        async with self.lock:
            old = next((j for j in self.jobs.values()
                        if j['operationKey'] == job['operationKey']), None)
            old = old or next((j for j in self.jobs.values() if slot(j) == slot(job)), None)
            if old:
                return deepcopy(existing(old, job))
            self.jobs[job['id']] = deepcopy(job)
            return deepcopy(job)

    async def change(self, job_id: str, change: Change) -> JsonObject:
        async with self.lock:
            if job_id not in self.jobs:
                raise DomainError('VIDEO_JOB_NOT_FOUND')
            job = deepcopy(self.jobs[job_id])
            change(job)
            job.pop('_enqueue', None)
            self.jobs[job_id] = job
            return deepcopy(job)

    async def finish(self, job_id: str, token: str, expected: JsonObject,
                     asset: JsonObject) -> JsonObject:
        async with self.lock:
            job = deepcopy(self.jobs[job_id])
            owns(job, token)
            record = await self.projects.get(job['projectId'])
            if record is None:
                raise DomainError('PROJECT_NOT_FOUND')
            asset = install(record.project, expected, asset)
            await self.projects.save(record)
            event(job, 'succeeded')
            job.update(result={'asset': asset, 'projectVersion': record.project['version']},
                       leaseToken=None, leaseUntil=0, error=None, errorDetail={})
            self.jobs[job_id] = job
            return deepcopy(job)

    async def adopt(self, project_id: str, job_id: str, expected: JsonObject) -> JsonObject:
        async with self.lock:
            job = deepcopy(self.jobs.get(job_id))
            if job is None or job.get('projectId') != project_id:
                raise DomainError('VIDEO_JOB_NOT_FOUND')
            if job.get('status') != 'succeeded' or not job.get('result', {}).get('asset'):
                raise DomainError('VIDEO_JOB_NOT_ADOPTABLE')
            if job['result']['asset'].get('valid'):
                return job
            record = await self.projects.get(project_id)
            if record is None:
                raise DomainError('PROJECT_NOT_FOUND')
            if record.project != expected:
                raise DomainError('VIDEO_JOB_CANDIDATE_STALE')
            asset = adopt_asset(record.project, job['result']['asset']['id'])
            await self.projects.save(record)
            job['result']['asset'] = deepcopy(asset)
            job['result']['projectVersion'] = record.project['version']
            self.jobs[job_id] = job
            return deepcopy(job)


class SqlVideoJobStore(VideoJobStore):
    def __init__(self, sessions: Any) -> None:
        self.sessions = sessions

    @staticmethod
    def enqueue(session: Any, job: JsonObject) -> None:
        session.add(OutboxRow(id=f'evt_{uuid4().hex}', topic='production.video.queued',
            payload={'jobId': job['id']}, status='pending', created_at=datetime.now(UTC)))

    async def get(self, job_id: str) -> JsonObject | None:
        async with self.sessions() as session:
            row = await session.get(VideoJobRow, job_id)
            return deepcopy(row.payload) if row else None

    async def list(self, project_id: str) -> list[JsonObject]:
        async with self.sessions() as session:
            rows = await session.scalars(select(VideoJobRow).where(
                VideoJobRow.project_id == project_id))
            return [deepcopy(row.payload) for row in rows]

    async def create(self, job: JsonObject) -> JsonObject:
        try:
            async with self.sessions.begin() as session:
                session.add(VideoJobRow(id=job['id'], project_id=job['projectId'],
                    operation_key=job['operationKey'], active_slot=slot(job),
                    revision=0, payload=deepcopy(job)))
                self.enqueue(session, job)
            return deepcopy(job)
        except IntegrityError:
            async with self.sessions() as session:
                row = await session.scalar(select(VideoJobRow).where(
                    VideoJobRow.operation_key == job['operationKey']))
                if row is None:
                    row = await session.scalar(select(VideoJobRow).where(
                        VideoJobRow.active_slot == slot(job)))
                if row is None:
                    raise DomainError('VIDEO_JOB_CONFLICT') from None
                return existing(deepcopy(row.payload), job)

    async def change(self, job_id: str, change: Change) -> JsonObject:
        for _ in range(8):
            async with self.sessions.begin() as session:
                row = await session.get(VideoJobRow, job_id)
                if row is None:
                    raise DomainError('VIDEO_JOB_NOT_FOUND')
                job: JsonObject = deepcopy(row.payload)
                change(job)
                enqueue = job.pop('_enqueue', False)
                result = await session.execute(update(VideoJobRow).where(
                    VideoJobRow.id == job_id, VideoJobRow.revision == row.revision
                ).values(payload=job, active_slot=slot(job), revision=row.revision + 1))
                if result.rowcount != 1:
                    continue
                if enqueue:
                    self.enqueue(session, job)
                return job
        raise DomainError('VIDEO_JOB_CONFLICT')

    async def finish(self, job_id: str, token: str, expected: JsonObject,
                     asset: JsonObject) -> JsonObject:
        async with self.sessions.begin() as session:
            row = await session.get(VideoJobRow, job_id, with_for_update=True)
            if row is None:
                raise DomainError('VIDEO_JOB_NOT_FOUND')
            job: JsonObject = deepcopy(row.payload)
            owns(job, token)
            project_row = await session.get(ProjectStateRow, job['projectId'], with_for_update=True)
            if project_row is None:
                raise DomainError('PROJECT_NOT_FOUND')
            payload = deepcopy(project_row.payload)
            asset = install(payload['project'], expected, asset)
            event(job, 'succeeded')
            job.update(result={'asset': asset, 'projectVersion': payload['project']['version']},
                       leaseToken=None, leaseUntil=0, error=None, errorDetail={})
            result = await session.execute(update(VideoJobRow).where(
                VideoJobRow.id == job_id, VideoJobRow.revision == row.revision
            ).values(payload=job, revision=row.revision + 1, active_slot=None))
            if result.rowcount != 1:
                raise DomainError('VIDEO_JOB_LEASE_LOST')
            result = await session.execute(update(ProjectStateRow).where(
                ProjectStateRow.id == project_row.id,
                ProjectStateRow.updated_at == project_row.updated_at,
            ).values(payload=payload, updated_at=datetime.now(UTC)))
            if result.rowcount != 1:
                raise DomainError('VIDEO_JOB_CONFLICT')
            return job

    async def adopt(self, project_id: str, job_id: str, expected: JsonObject) -> JsonObject:
        async with self.sessions.begin() as session:
            row = await session.get(VideoJobRow, job_id, with_for_update=True)
            if row is None or row.project_id != project_id:
                raise DomainError('VIDEO_JOB_NOT_FOUND')
            job: JsonObject = deepcopy(row.payload)
            if job.get('status') != 'succeeded' or not job.get('result', {}).get('asset'):
                raise DomainError('VIDEO_JOB_NOT_ADOPTABLE')
            if job['result']['asset'].get('valid'):
                return job
            project_row = await session.get(ProjectStateRow, project_id, with_for_update=True)
            if project_row is None:
                raise DomainError('PROJECT_NOT_FOUND')
            payload = deepcopy(project_row.payload)
            if payload['project'] != expected:
                raise DomainError('VIDEO_JOB_CANDIDATE_STALE')
            asset = adopt_asset(payload['project'], job['result']['asset']['id'])
            job['result']['asset'] = deepcopy(asset)
            job['result']['projectVersion'] = payload['project']['version']
            result = await session.execute(update(VideoJobRow).where(
                VideoJobRow.id == job_id, VideoJobRow.revision == row.revision
            ).values(payload=job, revision=row.revision + 1))
            if result.rowcount != 1:
                raise DomainError('VIDEO_JOB_CONFLICT')
            result = await session.execute(update(ProjectStateRow).where(
                ProjectStateRow.id == project_row.id,
                ProjectStateRow.updated_at == project_row.updated_at,
            ).values(payload=payload, updated_at=datetime.now(UTC)))
            if result.rowcount != 1:
                raise DomainError('VIDEO_JOB_CONFLICT')
            return job
