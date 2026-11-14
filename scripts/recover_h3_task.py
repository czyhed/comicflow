"""Recover an operator-verified existing task. Never submits or expands a prompt.

Confirm the project/shot/task association from logs before using --attach.
Run inside the API container so environment credentials and storage are available.
Default: query only. --attach requires --expected-version and preserves existing videos.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import httpx
from comicflow.domain.models import JsonObject
from comicflow.infrastructure.database import ProjectStateRow, create_session_factory
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from comicflow.providers.s3 import create_configured_asset_store
from comicflow.utils.frame_extractor import FrameExtractor
from sqlalchemy import select

MAX_VIDEO_BYTES = 200 * 1024 * 1024


def find_existing(project: JsonObject, shot_id: str, task_id: str) -> JsonObject | None:
    for asset in project.get('visualAssets', []):
        if asset.get('requestReference') == task_id:
            if asset.get('shotId') != shot_id:
                raise RuntimeError('H3_RECOVERY_TASK_MISMATCH')
            if not asset.get('valid'):
                raise RuntimeError('H3_RECOVERY_ASSET_INVALIDATED')
            return dict(asset)
    return None


def attach_asset(
    before: JsonObject, current: JsonObject, shot_id: str, asset: JsonObject,
) -> JsonObject:
    if current != before:
        raise RuntimeError('H3_RECOVERY_PROJECT_CHANGED')
    if any(a.get('shotId') == shot_id and a.get('valid')
           for a in current.get('visualAssets', [])):
        raise RuntimeError('H3_RECOVERY_EXISTING_VIDEO')
    result = deepcopy(current)
    result.setdefault('visualAssets', []).append(asset)
    result['exportManifest'] = None
    result['downstreamInvalidated'] = True
    return result


async def retrieve_existing(
    provider: MinimaxH3Provider, task_id: str, duration: int | float, *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[JsonObject, bytes]:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id):
        raise RuntimeError('H3_RECOVERY_TASK_MISMATCH')
    # The adapter's existing query parser is reused, never its generate method.
    async with httpx.AsyncClient(
        base_url=provider._base_url, timeout=30, transport=transport,
        headers={'Authorization': f'Bearer {provider._api_key}'},
    ) as client:
        task = await provider._poll(client, task_id)
    if (task.get('id') != task_id or task.get('duration') != duration
            or task.get('model') != provider._model):
        raise RuntimeError('H3_RECOVERY_TASK_MISMATCH')
    url = httpx.URL(provider._video_url(task))
    if url.scheme != 'https' or not url.host or url.username or url.password:
        raise RuntimeError('H3_RECOVERY_RESULT_URL_INVALID')
    async with httpx.AsyncClient(timeout=120, transport=transport) as download:
        async with download.stream('GET', url) as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > MAX_VIDEO_BYTES:
                    raise RuntimeError('H3_RECOVERY_VIDEO_TOO_LARGE')
                content.extend(chunk)
    return task, bytes(content)


async def verify_video(content: bytes, duration: int | float) -> tuple[bytes, bytes, JsonObject]:
    with tempfile.TemporaryDirectory(prefix='comicflow-h3-recovery-') as directory:
        path = Path(directory) / 'video.mp4'
        path.write_bytes(content)
        probe = await asyncio.to_thread(
            subprocess.run, ['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, check=True,
        )
        metadata = json.loads(probe.stdout)
        video = next((s for s in metadata['streams'] if s.get('codec_type') == 'video'), None)
        actual_duration = float(metadata['format']['duration'])
        if (not video or not video.get('width') or not video.get('height')
                or abs(actual_duration - duration) > 0.5):
            raise RuntimeError('H3_RECOVERY_MEDIA_INVALID')
        first = await FrameExtractor.extract_first_frame(path)
        last = await FrameExtractor.extract_last_frame(path)
        if not first or not last:
            raise RuntimeError('H3_RECOVERY_MEDIA_INVALID')
        return first, last, {
            'durationSec': actual_duration, 'width': video['width'], 'height': video['height'],
            'hasAudio': any(s.get('codec_type') == 'audio' for s in metadata['streams']),
        }


async def recover(args: argparse.Namespace) -> JsonObject:
    for value in (args.project, args.shot, args.task):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            raise RuntimeError('H3_RECOVERY_IDENTIFIER_INVALID')
    if args.attach and args.expected_version is None:
        raise RuntimeError('H3_RECOVERY_VERSION_REQUIRED')
    provider = MinimaxH3Provider(
        api_key=os.environ['MINIMAX_API_KEY'],
        base_url=os.getenv('MINIMAX_BASE_URL', 'https://cp.compshare.cn'),
        model=os.getenv('MINIMAX_VIDEO_MODEL', 'MiniMax-H3'),
        query_path=os.getenv(
            'MINIMAX_QUERY_PATH', '/minimax/v2/query/video_generation/{task_id}',
        ),
        timeout_seconds=180,
    )
    engine, sessions = create_session_factory(os.environ['DATABASE_URL'])
    try:
        async with sessions() as session:
            row = await session.get(ProjectStateRow, args.project)
            if row is None:
                raise RuntimeError('H3_RECOVERY_PROJECT_MISSING')
            before = deepcopy(row.payload['project'])
        existing = find_existing(before, args.shot, args.task)
        if existing:
            return {'status': 'already_attached', 'taskId': args.task, 'generationRequests': 0}
        if args.attach and before['version'] != args.expected_version:
            raise RuntimeError('H3_RECOVERY_PROJECT_CHANGED')
        shot = next((s for s in before.get('script', {}).get('shots', [])
                     if s.get('id') == args.shot), None)
        if shot is None:
            raise RuntimeError('H3_RECOVERY_SHOT_MISSING')
        if not args.attach:
            async with httpx.AsyncClient(
                base_url=provider._base_url, timeout=30,
                headers={'Authorization': f'Bearer {provider._api_key}'},
            ) as client:
                response = await client.get(provider._query_path.replace('{task_id}', args.task))
                response.raise_for_status()
                status = response.json().get('task', {}).get('status')
                return {'status': status if status in {'queued', 'running', 'succeeded',
                         'failed', 'cancelled'} else 'unknown', 'generationRequests': 0}
        # Check before downloads/uploads as well as under the final database lock.
        attach_asset(before, before, args.shot, {})
        task, content = await retrieve_existing(provider, args.task, shot['durationSec'])
        first, last, media = await verify_video(content, shot['durationSec'])
        store = create_configured_asset_store()
        prefix = f'videos/{args.project}/{args.shot}/{args.task}'
        keys = {'objectKey': prefix + '/video.mp4', 'firstFrameObjectKey': prefix + '/first.jpg',
                'lastFrameObjectKey': prefix + '/last.jpg'}
        for key, data, mime in (
            ('objectKey', content, 'video/mp4'), ('firstFrameObjectKey', first, 'image/jpeg'),
            ('lastFrameObjectKey', last, 'image/jpeg'),
        ):
            await store.put_bytes(keys[key], data, mime)
        asset = {
            'id': f'visual-{args.shot}-{args.task}', 'shotId': args.shot, 'valid': True,
            'type': 'dynamic-video', 'mediaType': 'video', 'provider': 'minimax',
            'modelVersion': task['model'], 'requestReference': args.task,
            'durationSec': shot['durationSec'], 'bytes': len(content), 'fallback': False,
            'inputVersion': before['version'], 'sceneId': shot.get('sceneId'),
            'characterReferenceIds': shot.get('characterIds', []), **keys,
            'recovery': {'source': 'existing-provider-task', 'promptMetadataAvailable': False,
                         'media': media},
        }
        async with sessions.begin() as session:
            row = await session.scalar(
                select(ProjectStateRow).where(ProjectStateRow.id == args.project).with_for_update(),
            )
            if row is None:
                raise RuntimeError('H3_RECOVERY_PROJECT_MISSING')
            existing = find_existing(row.payload['project'], args.shot, args.task)
            if existing:
                return {'status': 'already_attached', 'taskId': args.task, 'generationRequests': 0}
            project = attach_asset(before, row.payload['project'], args.shot, asset)
            row.payload = {**deepcopy(row.payload), 'project': project}
            row.updated_at = datetime.now(UTC)
        return {'status': 'attached', 'taskId': args.task, 'shotId': args.shot,
                **media, 'generationRequests': 0}
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--shot', required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--attach', action='store_true')
    parser.add_argument('--expected-version', type=int)
    try:
        print(json.dumps(asyncio.run(recover(parser.parse_args()))))
    except Exception as error:
        # Never print HTTP exceptions: they can contain a signed result URL.
        code = str(error)
        print(json.dumps({'error': code if re.fullmatch(r'[A-Z0-9_]{1,64}', code)
                          else 'H3_RECOVERY_FAILED', 'type': type(error).__name__}))
        raise SystemExit(1) from None
