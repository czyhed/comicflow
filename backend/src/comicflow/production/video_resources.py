"""Read-only video catalog: metadata first, storage access only on demand."""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore, ProjectRepository


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


class VideoResources:
    def __init__(self, repository: ProjectRepository, store: AssetStore | None) -> None:
        self.repository = repository
        self.store = store

    async def _project(self, project_id: str, user_id: str | None) -> JsonObject:
        record = await self.repository.get(project_id)
        if record is None:
            raise DomainError('PROJECT_NOT_FOUND')
        owner = record.project.get('ownerUserId')
        if owner is not None and owner != user_id:
            raise DomainError('PROJECT_ACCESS_DENIED')
        return record.project

    @staticmethod
    def _entries(project: JsonObject) -> list[JsonObject]:
        shots = {s['id']: s for s in (project.get('script') or {}).get('shots', [])}
        assets = [a for a in project.get('visualAssets', [])
                  if a.get('mediaType') == 'video' and isinstance(a.get('id'), str)]
        entries = []
        for index, asset in enumerate(assets):
            shot = shots.get(asset.get('shotId'))
            status = 'historical'
            if asset.get('status') == 'candidate':
                status = 'candidate'
            elif asset.get('valid') and shot:
                status = 'current'
            elif asset.get('invalidatedReason') in {'input-changed', 'dependency-changed'}:
                status = 'stale'
            created = timestamp(asset.get('createdAt'))
            duration = asset.get('durationMs')
            entries.append({
                'id': asset['id'], 'kind': 'shot', 'projectId': project['id'],
                'projectTitle': (project.get('script') or {}).get('title') or '未命名项目',
                'shotId': asset.get('shotId'),
                'title': asset.get('shotTitle') or (shot or {}).get('title') or '来源镜头已不可用',
                'sourceAvailable': shot is not None, 'status': status,
                'createdAt': created.isoformat() if created else None,
                'model': asset.get('modelVersion') or asset.get('model') or None,
                'durationMs': duration if isinstance(duration, (int, float)) and duration > 0
                else None,
                'fileState': 'unchecked' if asset.get('objectKey') else 'untracked',
                '_asset': asset, '_order': index,
            })
        manifest = project.get('exportManifest')
        if isinstance(manifest, dict):
            entries.append({
                'id': 'export:current', 'kind': 'export', 'projectId': project['id'],
                'projectTitle': (project.get('script') or {}).get('title') or '未命名项目',
                'title': '当前合成成片', 'shotId': None, 'sourceAvailable': True,
                'status': 'current', 'createdAt': None, 'model': None, 'durationMs': None,
                'fileState': 'unchecked' if (manifest.get('objectKeys') or {}).get('video.mp4')
                else 'untracked',
                '_asset': {'objectKey': (manifest.get('objectKeys') or {}).get('video.mp4'),
                           'firstFrameObjectKey':
                               (manifest.get('objectKeys') or {}).get('cover.jpg')},
                '_order': len(assets),
            })
        entries.sort(key=lambda a: (a['createdAt'] or '', a['_order']), reverse=True)
        return entries

    async def list(
        self, project_id: str, user_id: str | None, *, kind: str = 'all',
        shot_id: str | None = None, status: str = 'all', offset: int = 0, limit: int = 24,
    ) -> JsonObject:
        entries = self._entries(await self._project(project_id, user_id))
        entries = [e for e in entries if (kind == 'all' or e['kind'] == kind)
                   and (not shot_id or e['shotId'] == shot_id)
                   and (status == 'all' or e['status'] == status)]
        return {'items': [{k: v for k, v in e.items() if not k.startswith('_')}
                          for e in entries[offset:offset + limit]],
                'total': len(entries), 'offset': offset, 'limit': limit}

    async def access(
        self, project_id: str, asset_id: str, user_id: str | None, *, download: bool = False,
    ) -> JsonObject:
        entries = self._entries(await self._project(project_id, user_id))
        entry = next((e for e in entries if e['id'] == asset_id), None)
        if entry is None:
            raise DomainError('RESOURCE_NOT_FOUND')
        asset = entry['_asset']
        key = asset.get('objectKey')
        if not isinstance(key, str) or not key:
            raise DomainError('RESOURCE_FILE_UNTRACKED')
        if self.store is None:
            raise DomainError('RESOURCE_STORAGE_UNAVAILABLE')
        filename = 'video-' + re.sub(r'[^A-Za-z0-9_-]', '_', asset_id)[:100] + '.mp4'
        try:
            exists = await self.store.exists(key)
            if not exists:
                raise DomainError('RESOURCE_FILE_MISSING')
            url = (await self.store.presigned_download_url(key, filename, expires_in=900)
                   if download else await self.store.presigned_get_url(key, expires_in=900))
        except DomainError:
            raise
        except Exception:
            raise DomainError('RESOURCE_STORAGE_UNAVAILABLE') from None
        poster = None
        poster_key = asset.get('firstFrameObjectKey') or asset.get('lastFrameObjectKey')
        if not download and isinstance(poster_key, str):
            try:
                if await self.store.exists(poster_key):
                    poster = await self.store.presigned_get_url(poster_key, expires_in=900)
            except Exception:
                pass  # An optional poster must not hide an otherwise playable video.
        return {'url': url, 'posterUrl': poster, 'filename': filename,
                'expiresAt': (datetime.now(UTC) + timedelta(seconds=900)).isoformat()}
