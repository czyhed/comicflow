"""Shot audio, native soundtrack preparation and scoped lip-sync production."""
from __future__ import annotations

from copy import deepcopy

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject, ProjectRecord
from comicflow.media.timeline import build_dialogue, build_shot_timeline
from comicflow.production.interfaces import (
    AssetStore,
    LipSyncProvider,
    ProjectRepository,
    TtsProvider,
)
from comicflow.providers.error_mapping import map_provider_error


class AudioProduction:
    """Own audio asset/timeline updates, accepting only the dependencies they use."""

    def __init__(
        self, repository: ProjectRepository, tts_provider: TtsProvider,
        lip_sync_provider: LipSyncProvider, asset_store: AssetStore | None,
    ) -> None:
        self._repository = repository
        self._tts_provider = tts_provider
        self._lip_sync_provider = lip_sync_provider
        self._asset_store = asset_store

    async def generate_shot_audio(
        self, project_id: str, shot_id: str, *, expected_version: int
    ) -> JsonObject:
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        shot = self._require_shot(project, shot_id)
        visual = next(
            (
                item
                for item in project.get("visualAssets", [])
                if item["shotId"] == shot_id and item.get("valid")
            ),
            None,
        )
        if visual is None:
            raise DomainError("VISUAL_ASSET_REQUIRED")

        if visual.get('provider') == 'minimax' and visual.get('mediaType') == 'video':
            return await self._prepare_native_audio(record, shot, visual, expected_version)

        # Voice the shot line: dialogue when present, otherwise narration, so a
        # full film stays audible even for narration-only shots.
        text = str(shot.get("dialogue", "") or shot.get("narration", "")).strip()
        if not text:
            timeline = build_shot_timeline(shot=shot, visual_asset=visual)
            project.setdefault("timelines", {})[shot_id] = timeline
            await self._repository.save(record)
            return {
                "asset": None,
                "lipSync": None,
                "timeline": deepcopy(timeline),
                "projectVersion": project["version"],
            }

        character_ids = shot.get("characterIds") or ["narrator"]
        speaker_id = character_ids[0]
        try:
            audio = await self._tts_provider.generate(shot_id, speaker_id, text)
        except RuntimeError as error:
            raise DomainError(map_provider_error(str(error)), {'stage': 'tts'}) from error
        dialogue = build_dialogue(
            shot_id=shot_id,
            speaker_id=speaker_id,
            text=text,
            start_ms=0,
            duration_ms=int(audio["durationMs"]),
        )
        try:
            lip_sync = await self._lip_sync_provider.generate(shot_id, audio, dialogue)
        except RuntimeError as error:
            raise DomainError(map_provider_error(str(error)), {'stage': 'lip_sync'}) from error
        if (
            not isinstance(lip_sync.get("startMs"), int)
            or not isinstance(lip_sync.get("endMs"), int)
            or lip_sync["startMs"] < 0
            or lip_sync["endMs"] <= lip_sync["startMs"]
            or lip_sync["endMs"] > int(audio["durationMs"])
        ):
            raise RuntimeError("PROVIDER_RESPONSE_INVALID")
        dialogue["audioAssetId"] = audio["id"]
        dialogue["lipSyncAssetId"] = lip_sync["id"]
        timeline = build_shot_timeline(shot=shot, visual_asset=visual, dialogue=dialogue)
        timeline["lipSyncTrack"] = [
            {
                "assetId": lip_sync["id"],
                "startMs": lip_sync["startMs"],
                "endMs": lip_sync["endMs"],
            }
        ]
        audio_asset = {**audio, "valid": True}
        lip_sync_asset = {**lip_sync, "valid": True}
        for key, next_asset in (("audioAssets", audio_asset), ("lipSyncAssets", lip_sync_asset)):
            assets = project.setdefault(key, [])
            for asset in assets:
                if asset["shotId"] == shot_id and asset.get("valid"):
                    asset["valid"] = False
            assets.append(next_asset)
        project.setdefault("timelines", {})[shot_id] = timeline
        project["exportManifest"] = None
        project["downstreamInvalidated"] = True
        await self._repository.save(record)
        return {
            "asset": deepcopy(audio_asset),
            "lipSync": deepcopy(lip_sync_asset),
            "timeline": deepcopy(timeline),
            "projectVersion": project["version"],
        }

    async def _prepare_native_audio(
        self, record: ProjectRecord, shot: JsonObject, visual: JsonObject, expected_version: int,
    ) -> JsonObject:
        from comicflow.providers.native_audio import extract_native_audio

        project = record.project
        existing = next((item for item in project.get('audioAssets', [])
                         if item.get('valid') and item.get('source') == 'video-native'
                         and item.get('sourceVisualAssetId') == visual['id']
                         and item.get('shotId') == shot['id']), None)
        audio = existing
        if audio is None:
            try:
                audio = await extract_native_audio(self._asset_store, visual)
            except RuntimeError as error:
                raise DomainError(str(error), {'stage': 'native_audio'}) from error
            # Work on a fresh snapshot after file I/O; don't overwrite concurrent edits.
            record = await self._require_record(project['id'])
            project = record.project
            self._require_version(project, expected_version)
            if not any(item.get('id') == visual['id'] and item.get('valid')
                       for item in project.get('visualAssets', [])):
                raise DomainError('VERSION_CONFLICT')
            # A concurrent extraction may have already installed this same source.
            audio = next((item for item in project.get('audioAssets', [])
                          if item.get('valid') and item.get('source') == 'video-native'
                          and item.get('sourceVisualAssetId') == visual['id']
                          and item.get('shotId') == shot['id']), audio)
            if not any(item.get('id') == audio['id'] for item in project.get('audioAssets', [])):
                for item in project.setdefault('audioAssets', []):
                    if item.get('shotId') == shot['id']:
                        item['valid'] = False
                project['audioAssets'].append(audio)
            for item in project.get('lipSyncAssets', []):
                if item.get('shotId') == shot['id']:
                    item['valid'] = False
            project['exportManifest'] = None
            project['downstreamInvalidated'] = True
        text = '\n'.join(
            str(shot.get(key) or '').strip() for key in ('dialogue', 'narration')
        ).strip()
        dialogue = None
        if text:
            dialogue = build_dialogue(
                shot_id=shot['id'], speaker_id='video-native', text=text, start_ms=0,
                duration_ms=min(int(audio['durationMs']), round(float(shot['durationSec']) * 1000)),
            )
            dialogue['audioAssetId'] = audio['id']
        timeline = build_shot_timeline(shot=shot, visual_asset=visual, dialogue=dialogue)
        project.setdefault('timelines', {})[shot['id']] = timeline
        await self._repository.save(record)
        return {'asset': deepcopy(audio), 'lipSync': None, 'timeline': deepcopy(timeline),
                'projectVersion': project['version'], 'reused': existing is not None}

    async def regenerate_lip_sync(
        self, project_id: str, shot_id: str, *, expected_version: int,
    ) -> JsonObject:
        scope = "lipsync"
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        shot = self._require_shot(project, shot_id)
        visual = next(
            (
                item
                for item in project.get("visualAssets", [])
                if item["shotId"] == shot_id and item.get("valid")
            ),
            None,
        )
        if visual is None:
            raise DomainError("VISUAL_ASSET_REQUIRED")
        text = str(shot.get("dialogue", "")).strip()
        if not text:
            return {
                "scope": scope,
                "asset": None,
                "lipSync": None,
                "timeline": deepcopy(project.get("timelines", {}).get(shot_id, {})),
                "projectVersion": project["version"],
            }
        speaker_id = (shot.get("characterIds") or ["narrator"])[0]
        audio = next(
            (
                item
                for item in project.get("audioAssets", [])
                if item["shotId"] == shot_id and item.get("valid")
            ),
            None,
        )
        if audio is None:
            raise DomainError("AUDIO_ASSET_REQUIRED")
        dialogue = build_dialogue(
            shot_id=shot_id,
            speaker_id=speaker_id,
            text=text,
            start_ms=0,
            duration_ms=int(audio["durationMs"]),
        )
        lip_sync = await self._lip_sync_provider.generate(shot_id, audio, dialogue)
        dialogue["audioAssetId"] = audio["id"]
        dialogue["lipSyncAssetId"] = lip_sync["id"]
        timeline = build_shot_timeline(shot=shot, visual_asset=visual, dialogue=dialogue)
        timeline["lipSyncTrack"] = [
            {"assetId": lip_sync["id"], "startMs": lip_sync["startMs"], "endMs": lip_sync["endMs"]}
        ]
        for asset in project.setdefault("lipSyncAssets", []):
            if asset["shotId"] == shot_id and asset.get("valid"):
                asset["valid"] = False
        lip_sync_asset = {**lip_sync, "valid": True}
        project["lipSyncAssets"].append(lip_sync_asset)
        project.setdefault("timelines", {})[shot_id] = timeline
        project["exportManifest"] = None
        project["downstreamInvalidated"] = True
        await self._repository.save(record)
        return {
            "scope": scope,
            "asset": deepcopy(audio),
            "lipSync": deepcopy(lip_sync_asset),
            "timeline": deepcopy(timeline),
            "projectVersion": project["version"],
        }

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
