"""Composition job lifecycle and export manifests behind the existing Pipeline entry points."""
from __future__ import annotations

import math
from copy import deepcopy
from uuid import uuid4

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject, ProjectRecord
from comicflow.production.interfaces import AssetStore, CompositionProvider, ProjectRepository


class CompositionJobs:
    """Own composition orchestration; media encoding stays in the Provider."""

    def __init__(
        self, repository: ProjectRepository, composition_provider: CompositionProvider,
        asset_store: AssetStore | None, *, model_config_revision: int,
    ) -> None:
        self._repository = repository
        self._composition_provider = composition_provider
        self._asset_store = asset_store
        self._model_config_revision = model_config_revision

    @staticmethod
    def _composition_readiness(project: JsonObject) -> JsonObject:
        """Report which shots still lack the assets the delivery film needs.

        H3 footage carries its own soundtrack; FFmpeg validates the real audio
        stream during composition. Other speaking shots require a voice asset.
        This gate never generates replacement audio or asserts that speech matches text.
        """
        script = project.get("script")
        shots = script.get("shots") if isinstance(script, dict) else None
        if not isinstance(shots, list) or not shots:
            return {"missingVisualShotIds": [], "missingAudioShotIds": [], "shotCount": 0}

        def valid_shot_ids(key: str) -> set[str]:
            assets = project.get(key)
            if not isinstance(assets, list):
                return set()
            return {
                str(asset.get("shotId"))
                for asset in assets
                if isinstance(asset, dict) and asset.get("valid")
            }

        with_visual = valid_shot_ids("visualAssets")
        with_audio = valid_shot_ids("audioAssets")
        visuals = {
            str(asset.get("shotId")): asset
            for asset in project.get("visualAssets", [])
            if isinstance(asset, dict) and asset.get("valid")
        }
        missing_visual: list[str] = []
        missing_audio: list[str] = []
        for shot in shots:
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("id"))
            if shot_id not in with_visual:
                missing_visual.append(shot_id)
            speaks = bool(str(shot.get("dialogue", "") or shot.get("narration", "")).strip())
            visual = visuals.get(shot_id, {})
            native_audio = (
                visual.get("provider") == "minimax" and visual.get("mediaType") == "video"
            )
            if speaks and not native_audio and shot_id not in with_audio:
                missing_audio.append(shot_id)
        return {
            "missingVisualShotIds": missing_visual,
            "missingAudioShotIds": missing_audio,
            "shotCount": len(shots),
        }

    async def request_composition(
        self,
        project_id: str,
        *,
        expected_version: int,
        idempotency_key: str | None = None,
        shot_ids: list[str] | None = None,
        shot_trims: JsonObject | None = None,
    ) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        if idempotency_key:
            existing = next(
                (
                    job
                    for job in record.jobs
                    if job["type"] == "composition" and job.get("idempotencyKey") == idempotency_key
                ),
                None,
            )
            if existing:
                return deepcopy(existing)
        selected = self._selected_project(project, shot_ids) if shot_ids is not None else project
        self._validate_trims(selected, shot_trims or {})
        readiness = self._composition_readiness(selected)
        if readiness["missingVisualShotIds"] or readiness["missingAudioShotIds"]:
            raise DomainError("ASSETS_INCOMPLETE", readiness)
        job: JsonObject = {
            "id": f"job_{uuid4().hex[:12]}",
            "modelConfigRevision": self._model_config_revision,
            "projectId": project_id,
            "type": "composition",
            "status": "queued",
            "progress": 0,
            "inputVersion": project["version"],
            "idempotencyKey": idempotency_key,
        }
        if shot_ids is not None:
            job['shotIds'] = [shot['id'] for shot in selected['script']['shots']]
        if shot_trims:
            job['shotTrims'] = deepcopy(shot_trims)
        credit_cost = 20
        balance = sum(int(event.get("amount", 0)) for event in project.get("creditLedger", []))
        if balance < credit_cost:
            raise DomainError("INSUFFICIENT_CREDIT")
        project.setdefault("creditLedger", []).append(
            {"type": "reservation", "amount": -credit_cost, "jobId": job["id"]}
        )
        record.jobs.append(job)
        await self._repository.save(
            record,
            outbox_event={
                "topic": "production.job.queued",
                "payload": {"jobId": job["id"], "projectId": project_id},
            },
        )
        return deepcopy(job)

    @staticmethod
    def _validate_trims(project: JsonObject, trims: JsonObject) -> None:
        if not trims:
            return
        shot_ids = {s['id'] for s in (project.get('script') or {}).get('shots', [])}
        videos = {a.get('shotId') for a in project.get('visualAssets', [])
                  if a.get('valid') and a.get('mediaType') == 'video'}
        for sid, trim in trims.items():
            if sid not in shot_ids or sid not in videos or not isinstance(trim, dict):
                raise DomainError('COMPOSITION_TRIM_INVALID')
            start, end = trim.get('inSec'), trim.get('outSec')
            if (set(trim) != {'inSec', 'outSec'} or isinstance(start, bool)
                    or isinstance(end, bool) or not isinstance(start, (int, float))
                    or not isinstance(end, (int, float))):
                raise DomainError('COMPOSITION_TRIM_INVALID')
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise DomainError('COMPOSITION_TRIM_INVALID')

    @staticmethod
    def _selected_project(project: JsonObject, shot_ids: list[str]) -> JsonObject:
        shots = project.get('script', {}).get('shots', [])
        wanted = set(shot_ids)
        if not wanted or len(wanted) != len(shot_ids) or not wanted <= {s['id'] for s in shots}:
            raise DomainError('COMPOSITION_SHOTS_INVALID')
        selected = deepcopy(project)
        selected['script']['shots'] = sorted(
            [shot for shot in selected['script']['shots'] if shot['id'] in wanted],
            key=lambda shot: shot.get('order', 0),
        )
        for scene in selected['script'].get('scenes', []):
            scene['shotIds'] = [sid for sid in scene.get('shotIds', []) if sid in wanted]
        for key in ('visualAssets', 'audioAssets', 'lipSyncAssets'):
            selected[key] = [asset for asset in selected.get(key, [])
                             if asset.get('shotId') in wanted]
        selected['timelines'] = {sid: value for sid, value in selected.get('timelines', {}).items()
                                 if sid in wanted}
        return selected

    async def run_job(self, job_id: str) -> JsonObject:
        record = await self._repository.find_by_job(job_id)
        if record is None:
            raise DomainError("JOB_NOT_FOUND")
        job = next(item for item in record.jobs if item["id"] == job_id)
        if job["status"] in {"cancelled", "running", "succeeded", "stale"}:
            return deepcopy(job)
        if job["status"] not in ("queued", "failed"):
            raise DomainError("JOB_NOT_RUNNABLE")
        if record.project["version"] != job["inputVersion"]:
            job.update(status="stale", error="INPUT_VERSION_CHANGED")
            await self._repository.save(record)
            return deepcopy(job)
        claimed = await self._repository.claim_job(job_id)
        if claimed is None:
            latest = await self._repository.find_by_job(job_id)
            if latest is None:
                raise DomainError("JOB_NOT_FOUND")
            latest_job = next(item for item in latest.jobs if item["id"] == job_id)
            if latest_job["status"] in {"cancelled", "succeeded", "stale"}:
                return deepcopy(latest_job)
            raise DomainError("JOB_NOT_RUNNABLE")
        record = claimed
        job = next(item for item in record.jobs if item["id"] == job_id)
        partial = job.get('shotIds') is not None
        try:
            source = (self._selected_project(record.project, job['shotIds'])
                      if partial else record.project)
            if job.get('shotTrims'):
                self._validate_trims(source, job['shotTrims'])
                source = {**source, 'compositionTrims': deepcopy(job['shotTrims'])}
            readiness = self._composition_readiness(source)
            if readiness['missingVisualShotIds'] or readiness['missingAudioShotIds']:
                raise DomainError('ASSETS_INCOMPLETE', readiness)
            manifest = await self._composition_provider.compose(source)
            required_files = {"video.mp4", "cover.jpg", "subtitles.srt"}
            if set(manifest.get("files", [])) != required_files:
                raise DomainError("EXPORT_PACKAGE_INCOMPLETE")
            artifacts = manifest.get("artifacts", {})
            manifest = {key: value for key, value in manifest.items() if key != "artifacts"}
            if self._asset_store is not None:
                downloads: dict[str, str] = {}
                object_keys: dict[str, str] = {}
                for filename in sorted(required_files):
                    prefix = (f"exports/{record.project['id']}/previews/{job_id}"
                              if partial else f"exports/{record.project['id']}")
                    object_key = f"{prefix}/{filename}"
                    content_type = {
                        "video.mp4": "video/mp4",
                        "cover.jpg": "image/jpeg",
                        "subtitles.srt": "application/x-subrip",
                    }[filename]
                    content = artifacts.get(filename) if isinstance(artifacts, dict) else None
                    if not isinstance(content, bytes):
                        raise DomainError("EXPORT_ARTIFACT_MISSING")
                    await self._asset_store.put_bytes(object_key, content, content_type)
                    object_keys[filename] = object_key
                    downloads[filename] = await self._asset_store.presigned_get_url(object_key)
                manifest = {**manifest, "downloads": downloads, "objectKeys": object_keys}
            if partial:
                manifest.update(scope='selected', shotIds=deepcopy(job['shotIds']), jobId=job_id)
            if job.get('shotTrims'):
                manifest['shotTrims'] = deepcopy(job['shotTrims'])
            job.update(status="succeeded", progress=100, exportManifest=deepcopy(manifest))
            if not partial:
                record.project["exportManifest"] = deepcopy(manifest)
                record.project["downstreamInvalidated"] = False
            if not partial and record.project.get("input", {}).get("mode") == "automatic":
                record.project["stage"] = "exported"
                session = record.project.setdefault("generationSession", {})
                session.update({"stage": "exported", "status": "completed"})
        except Exception as error:
            job.update(status="failed", error=str(error))
            if not partial and record.project.get("input", {}).get("mode") == "automatic":
                session = record.project.setdefault("generationSession", {})
                session.update(
                    {
                        "stage": record.project.get("stage", "composition-queued"),
                        "status": "waiting-retry",
                        "lastError": str(error),
                    }
                )
            ledger = record.project.setdefault("creditLedger", [])
            if not any(
                entry.get("type") == "release" and entry.get("jobId") == job["id"]
                for entry in ledger
            ):
                ledger.append(
                    {
                        "type": "release",
                        "amount": 20,
                        "reason": "provider-failed",
                        "jobId": job["id"],
                    }
                )
        else:
            record.project.setdefault("creditLedger", []).append(
                {
                    "type": "settlement",
                    "amount": 0,
                    "consumed": 20,
                    "jobId": job["id"],
                }
            )
        await self._repository.save(record)
        return deepcopy(job)

    async def get_export_manifest(
        self, project_id: str, *, job_id: str | None = None,
    ) -> JsonObject:
        record = await self._require_record(project_id)
        if job_id is not None:
            job = next((item for item in record.jobs
                        if item['id'] == job_id and item['type'] == 'composition'), None)
            if job is None:
                raise DomainError('JOB_NOT_FOUND')
            manifest = job.get('exportManifest') if job['status'] == 'succeeded' else None
        else:
            manifest = record.project.get("exportManifest")
        if not isinstance(manifest, dict):
            raise DomainError("EXPORT_NOT_READY")
        refreshed = deepcopy(manifest)
        keys = refreshed.get("objectKeys")
        if self._asset_store is not None and isinstance(keys, dict):
            refreshed["downloads"] = {
                filename: await self._asset_store.presigned_get_url(object_key)
                for filename, object_key in keys.items()
                if isinstance(filename, str) and isinstance(object_key, str)
            }
        return refreshed

    async def cancel_job(self, job_id: str) -> JsonObject:
        record = await self._repository.find_by_job(job_id)
        if record is None:
            raise DomainError("JOB_NOT_FOUND")
        job = next(item for item in record.jobs if item["id"] == job_id)
        if job["status"] == "cancelled":
            return deepcopy(job)
        if job["status"] not in ("queued", "running", "failed"):
            raise DomainError("JOB_NOT_CANCELLABLE")
        job["status"] = "cancelled"
        ledger = record.project.setdefault("creditLedger", [])
        has_release = any(
            entry.get("type") == "release" and entry.get("jobId") == job_id for entry in ledger
        )
        has_reservation = any(
            entry.get("type") == "reservation" and entry.get("jobId") == job_id for entry in ledger
        )
        if has_reservation and not has_release:
            ledger.append({"type": "release", "amount": 20, "reason": "cancelled", "jobId": job_id})
        await self._repository.save(record)
        return deepcopy(job)

    async def _require_record(self, project_id: str) -> ProjectRecord:
        record = await self._repository.get(project_id)
        if record is None:
            raise DomainError("PROJECT_NOT_FOUND")
        return record

    @staticmethod
    def _require_version(project: JsonObject, expected_version: int) -> None:
        if project["version"] != expected_version:
            raise DomainError("VERSION_CONFLICT")
