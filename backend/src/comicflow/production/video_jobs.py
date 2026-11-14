"""Video execution owns checkpoints; recovery never repeats an uncertain submission."""
from __future__ import annotations

import logging
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject
from comicflow.infrastructure.video_jobs import TERMINAL, VideoJobStore
from comicflow.production.interfaces import (
    AssetStore,
    DynamicVisualProvider,
    PreviewableVisualProvider,
    ProjectRepository,
    TextProvider,
)
from comicflow.production.video_frames import extract_cascade_frames
from comicflow.production.video_preparation import VideoPreparation
from comicflow.production.visual_preflight import (
    adapter_identity,
    build_preflight,
    digest,
    display,
    stable,
)
from comicflow.providers.error_mapping import map_provider_error
from comicflow.providers.h3_errors import H3BusinessError, H3TaskError
from comicflow.providers.h3_skill import H3PromptValidationError
from comicflow.providers.text_errors import TextRequestError


def configuration(
    provider: DynamicVisualProvider, text: TextProvider, include_text: bool,
) -> str:
    selected_text: Any = text
    if include_text and hasattr(selected_text, 'selection'):
        selected_text = selected_text.selection.provider('video-prompt', selected_text.fallback)
    return digest({'video': adapter_identity(provider),
                   'text': adapter_identity(selected_text) if include_text else None})


def public_job(job: JsonObject) -> JsonObject:
    result = {key: deepcopy(job.get(key)) for key in (
        'id', 'projectId', 'shotId', 'status', 'taskId', 'createdAt', 'updatedAt',
        'modelConfigRevision', 'error', 'errorDetail', 'callsStarted', 'attempts', 'history',
    )}
    expired = job.get('leaseUntil', 0) <= time.time()
    if expired and job['status'] in {'submitting', 'expanding'} and not job.get('taskId'):
        result['status'] = 'unknown'
        result['error'] = 'VIDEO_SUBMISSION_UNKNOWN'
    result['canRecover'] = expired and job['status'] not in TERMINAL and bool(
        job.get('taskId') or job.get('asset') or
        job['status'] in {'queued', 'preparing', 'prepared', 'rendering'} or
        (job['status'] == 'recoverable' and job.get('resumeStage') in
         {'queued', 'preparing', 'prepared', 'rendering'})
    )
    result['canLinkTask'] = expired and result['status'] == 'unknown' and bool(
        job.get('compiled') and not job.get('taskId'))
    result['model'] = job['preflight'].get('model')
    result['parameters'] = deepcopy(job['preflight'].get('parameters'))
    result['result'] = None
    if job.get('result'):
        result['result'] = {
            'assetId': job['result']['asset']['id'],
            'adopted': bool(job['result']['asset'].get('valid')),
            'projectVersion': job['result']['projectVersion'],
        }
    return result


def safe_error(error: Exception) -> tuple[str, JsonObject]:
    if isinstance(error, TextRequestError):
        status = error.detail.get('upstreamStatus')
        logging.getLogger(__name__).warning(
            'Video text failed: stage=h3_text code=%s upstream_status=%s',
            map_provider_error(str(error)),
            status if isinstance(status, int) and 100 <= status <= 599 else None)
    if isinstance(error, DomainError):
        return error.code, deepcopy(error.detail)
    if isinstance(error, H3PromptValidationError):
        return 'H3_PROMPT_INVALID', {'reason': error.reason,
                                    **({'section': error.section} if error.section else {})}
    if isinstance(error, RuntimeError):
        return map_provider_error(str(error)), deepcopy(getattr(error, 'detail', {}))
    return 'VIDEO_JOB_EXECUTION_FAILED', {}


def execution_rules(preview: JsonObject) -> str:
    return digest(display({key: preview.get(key) for key in
                           ('model', 'mode', 'parameters', 'prompt', 'calls')}))


def freeze(value: Any) -> Any:
    value = stable(value)
    if isinstance(value, dict):
        return {k: freeze(v) for k, v in value.items()}
    if isinstance(value, list):
        return [freeze(v) for v in value]
    if isinstance(value, str) and 'data:image/' in value:
        raise DomainError('VIDEO_JOB_INLINE_IMAGE_UNSUPPORTED')
    return value


async def refresh_images(value: Any, store: AssetStore | None) -> Any:
    value = deepcopy(value)
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key.lower().endswith('objectkey') and isinstance(item, str) and item:
                url_key = key[:-9] + 'Url' if key != 'objectKey' else 'url'
                if store is None:
                    raise DomainError('REFERENCE_STORAGE_UNAVAILABLE')
                value[url_key] = await store.presigned_get_url(item, expires_in=900)
            else:
                value[key] = await refresh_images(item, store)
    elif isinstance(value, list):
        value = [await refresh_images(v, store) for v in value]
    return value


class VideoJobs:
    def __init__(
        self, *, store: VideoJobStore, preparation: VideoPreparation,
        repository: ProjectRepository, provider: DynamicVisualProvider,
        text_provider: TextProvider, asset_store: AssetStore | None,
        model_config_revision: int,
    ) -> None:
        self.store = store
        self._preparation = preparation
        self._repository = repository
        self._provider = provider
        self._text_provider = text_provider
        self._asset_store = asset_store
        self._model_config_revision = model_config_revision

    async def require(self, project_id: str, job_id: str) -> JsonObject:
        job = await self.store.get(job_id)
        if job is None or job['projectId'] != project_id:
            raise DomainError('VIDEO_JOB_NOT_FOUND')
        return job

    async def request(self, project_id: str, shot_id: str, *, expected_version: int,
                      operation_id: str, preflight_fingerprint: str | None = None,
                      continuity_mode: str = 'auto') -> JsonObject:
        operation_key = digest([project_id, shot_id, operation_id])
        prior = await self.store.operation(project_id, operation_key)
        if prior is not None:
            return prior
        record, shot, characters, cascade = await self._preparation.prepare(
            project_id, shot_id, expected_version=expected_version, continuity_mode=continuity_mode)
        prepared = await build_preflight(self._provider, self._text_provider,
            record.project, shot, characters, self._model_config_revision, self._asset_store)
        if preflight_fingerprint is not None and preflight_fingerprint != prepared['fingerprint']:
            raise DomainError('PREFLIGHT_STALE')
        if not prepared['ready']:
            raise DomainError(prepared['errors'][0], prepared.get('errorDetail') or
                              {'stage': 'preflight'})
        now = datetime.now(UTC).isoformat()
        job: JsonObject = {
            'id': f'vjob_{uuid4().hex}', 'projectId': project_id, 'shotId': shot_id,
            'operationKey': operation_key,
            'slot': digest([project_id, shot_id]), 'fingerprint': prepared['fingerprint'],
            'status': 'queued', 'createdAt': now, 'updatedAt': now, 'history': [],
            'modelConfigRevision': self._model_config_revision, 'preflight': prepared,
            'configSignature': configuration(
                self._provider, self._text_provider, bool(prepared['calls']['text'])),
            'executionRules': execution_rules(prepared),
            'shot': freeze(shot), 'characters': freeze(characters), 'cascadeFrom': cascade,
            'leaseSeconds': max(
                900, float(getattr(self._provider, '_timeout', 600)) + 120),
            'leaseToken': None, 'leaseUntil': 0, 'attempts': 0,
            'callsStarted': {'text': 0, 'video': 0},
            'requireAdoption': True,
        }
        try:
            return await self.store.create(job)
        except SQLAlchemyError:
            raise DomainError('VIDEO_JOB_STORAGE_UNAVAILABLE') from None

    async def run(self, job_id: str) -> JsonObject:
        token = uuid4().hex
        job = await self.store.claim(job_id, token)
        if job is None:
            stored = await self.store.get(job_id)
            if stored is None:
                raise DomainError('VIDEO_JOB_NOT_FOUND')
            return stored

        async def checkpoint(status: str, fields: JsonObject | None = None) -> None:
            nonlocal job
            job = await self.store.checkpoint(job_id, token, status, fields)

        try:
            if (not job.get('asset') and
                    configuration(self._provider, self._text_provider,
                                  bool(job['preflight']['calls']['text'])) !=
                    job['configSignature']):
                raise DomainError('VIDEO_JOB_CONFIG_CHANGED')
            if job.get('asset'):
                generated = deepcopy(job['asset'])
            else:
                shot, characters = job['shot'], job['characters']
                if not job.get('taskId'):
                    shot = await refresh_images(shot, self._asset_store)
                    characters = await refresh_images(characters, self._asset_store)
                provider = self._provider
                if not job.get('taskId') and not job.get('compiled'):
                    # Request preflight has already required this capability.
                    preview = cast(PreviewableVisualProvider, provider).prepare_preview(
                        shot, characters)
                    if execution_rules(preview) != job['executionRules']:
                        raise DomainError('VIDEO_JOB_CONFIG_CHANGED')
                shot = {**shot, 'providerIdempotencyKey': f"comicflow-{job['id']}"}
                from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
                from comicflow.providers.minimax_h3 import MinimaxH3Provider
                if isinstance(provider, (MinimaxH3Provider, BailianImageToVideoProvider)):
                    generated = await provider.generate(shot, characters, checkpoint=checkpoint,
                                                         resume=deepcopy(job))
                else:
                    await checkpoint('rendering')  # Only explicitly configured Mock reaches here.
                    generated = await provider.generate(shot, characters)
                await checkpoint('finalizing', {'asset': generated})
            current = await self._repository.get(job['projectId'])
            if current is None:
                raise DomainError('PROJECT_NOT_FOUND')
            try:
                fresh = await self._preparation.preview(job['projectId'], job['shotId'],
                    expected_version=current.project['version'],
                    continuity_mode=job['shot'].get('continuityMode', 'auto'))
            except DomainError:
                # Deleted/edited shots must not discard a paid result.
                fresh = {}
            asset: JsonObject = {
                **generated, 'shotId': job['shotId'], 'jobId': job['id'],
                'valid': (fresh.get('fingerprint') == job['fingerprint']
                          and not job.get('requireAdoption', True)),
                'createdAt': datetime.now(UTC).isoformat(), 'shotTitle': job['shot'].get('title'),
                'inputVersion': job['preflight']['projectVersion'],
                'modelConfigRevision': job['modelConfigRevision'],
                'preflightFingerprint': job['fingerprint'],
                'requestedParameters': deepcopy(job['preflight']['parameters']),
            }
            if job['preflight'].get('style'):
                asset['styleSnapshot'] = deepcopy(job['preflight']['style'])
                asset['styleApplication'] = {'engine': 'local-style-v1', 'stage': 'video'}
            for key in ('sceneId', 'characterIds'):
                if key in job['shot']:
                    asset_key = 'characterReferenceIds' if key == 'characterIds' else key
                    asset[asset_key] = job['shot'][key]
            if job.get('cascadeFrom'):
                asset['cascadeFromShotId'] = job['cascadeFrom']
            if asset.get('mediaType') == 'video' and self._asset_store is not None:
                await extract_cascade_frames(self._asset_store, asset, job['shotId'])
            return await self.store.finish(job_id, token, current.project, asset)
        except Exception as error:
            # Cancellation/process death leaves the last checkpoint and lease intact.
            if isinstance(error, DomainError) and error.code == 'VIDEO_JOB_LEASE_LOST':
                raise
            code, detail = safe_error(error)
            status = 'failed'
            if job.get('taskId') or job.get('asset'):
                status = 'failed' if isinstance(error, H3TaskError) or getattr(
                    error, 'terminal', False) else 'recoverable'
            elif job['status'] == 'submitting':
                rejected = isinstance(error, H3BusinessError) or (
                    hasattr(error, 'detail')
                    and 400 <= error.detail.get('upstreamStatus', 0) < 500)
                status = 'failed' if rejected else 'unknown'
            elif job['status'] == 'expanding' and (
                isinstance(error, SQLAlchemyError) or code == 'PROVIDER_TIMEOUT'
                or code == 'VIDEO_JOB_EXECUTION_FAILED'
            ):
                status = 'unknown'
            elif isinstance(error, SQLAlchemyError):
                status = 'unknown' if job['status'] == 'expanding' else 'recoverable'
            return await self.store.checkpoint(job_id, token, status, {
                'error': code, 'errorDetail': detail, 'resumeStage': job['status'],
            })

    async def adopt(self, project_id: str, job_id: str) -> JsonObject:
        job = await self.require(project_id, job_id)
        if job.get('status') != 'succeeded' or not job.get('result', {}).get('asset'):
            raise DomainError('VIDEO_JOB_NOT_ADOPTABLE')
        # Replaying the same adoption never reinstalls a superseded historical version.
        if job['result']['asset'].get('valid'):
            return job
        record = await self._repository.get(project_id)
        if record is None:
            raise DomainError('PROJECT_NOT_FOUND')
        try:
            prepared_record, shot, characters, _ = await self._preparation.prepare(
                project_id, job['shotId'], expected_version=record.project['version'],
                continuity_mode=job['shot'].get('continuityMode', 'auto'))
            current = await build_preflight(self._provider, self._text_provider,
                prepared_record.project, shot, characters, self._model_config_revision,
                self._asset_store)
        except DomainError:
            raise DomainError('VIDEO_JOB_CANDIDATE_STALE') from None
        if not current.get('ready') or current.get('fingerprint') != job.get('fingerprint'):
            raise DomainError('VIDEO_JOB_CANDIDATE_STALE')
        asset = job['result']['asset']
        if self._asset_store is not None:
            try:
                object_key = asset.get('objectKey')
                exists = bool(object_key) and await self._asset_store.exists(object_key)
            except Exception:
                raise DomainError('RESOURCE_STORAGE_UNAVAILABLE') from None
            if not exists:
                raise DomainError('VIDEO_JOB_CANDIDATE_MISSING')
        return await self.store.adopt(project_id, job_id, prepared_record.project)

    async def recover(self, project_id: str, job_id: str, task_id: str | None = None) -> JsonObject:
        await self.require(project_id, job_id)
        if task_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id):
            raise DomainError('VIDEO_JOB_TASK_INVALID')
        return await self.store.recover(job_id, task_id)
