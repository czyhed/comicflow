import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock_media import MockDynamicVisualProvider


class _InternalOnlyStore:
    """Asset store whose presigned URLs point at an unreachable public endpoint.

    Mirrors the deployed topology: ``S3_PUBLIC_ENDPOINT`` is a host-only address,
    so any in-process HTTP fetch of a presigned URL fails. Only ``get_bytes``
    works from inside the API container.
    """

    def __init__(self, video_bytes: bytes) -> None:
        self._objects = {'videos/s1/v1.mp4': video_bytes}
        self.put: dict[str, bytes] = {}
        self.presigned_calls: list[str] = []

    async def presigned_get_url(self, key, expires_in=900):
        self.presigned_calls.append(key)
        return f'http://127.0.0.1:19000/comicflow/{key}'

    async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
        if key not in self._objects:
            raise KeyError(key)
        return self._objects[key]

    async def put_bytes(self, key, content, content_type):
        self.put[key] = content
        return key


def _fake_mp4() -> bytes:
    return b'\x00\x00\x00\x18ftypmp42' + b'\x00' * 64


@pytest.mark.asyncio
async def test_frame_extraction_reads_video_through_internal_store(monkeypatch):
    """Frame extraction must not depend on the public presigned endpoint."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，小雨在公交车里等待姐姐。',
        mode='import_story', duration_sec=30,
    ))
    project_id = created['project']['id']
    record = await pipeline._repository.get(project_id)
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1']}],
        'shots': [{'id': 's1', 'durationSec': 5, 'visualDescription': '公交车驶过雨夜',
                   'characterIds': []}],
        'version': 1,
    }
    record.project['visualAssets'] = []
    await pipeline._repository.save(record)
    store = _InternalOnlyStore(_fake_mp4())
    pipeline._asset_store = store

    seen_paths: list[str] = []

    async def fake_first(path):
        seen_paths.append(str(path))
        return b'\xff\xd8\xff-first'

    async def fake_last(path):
        seen_paths.append(str(path))
        return b'\xff\xd8\xff-last'

    from comicflow.utils import frame_extractor

    monkeypatch.setattr(frame_extractor.FrameExtractor, 'extract_first_frame', fake_first)
    monkeypatch.setattr(frame_extractor.FrameExtractor, 'extract_last_frame', fake_last)

    class Provider(MockDynamicVisualProvider):
        async def generate(self, shot, characters):
            return {
                'id': 'v1', 'shotId': 's1', 'type': 'dynamic', 'mediaType': 'video',
                'objectKey': 'videos/s1/v1.mp4', 'provider': 'test',
            }

    pipeline.set_video_provider(Provider())
    result = await pipeline.generate_shot_visual(
        project_id, 's1', expected_version=record.project['version']
    )

    asset = result['asset']
    assert asset['firstFrameObjectKey'].startswith('visuals/s1/')
    assert asset['firstFrameObjectKey'].endswith('/first_frame.jpg')
    assert asset['lastFrameObjectKey'].endswith('/last_frame.jpg')
    assert store.put[asset['lastFrameObjectKey']] == b'\xff\xd8\xff-last'
    assert seen_paths, 'frame extractor was never invoked'
    # The video must be fetched internally, never through the public presigned host.
    assert 'videos/s1/v1.mp4' not in store.presigned_calls


async def test_same_shot_id_in_different_videos_has_independent_frames(monkeypatch):
    from comicflow.production.video_frames import extract_cascade_frames
    from comicflow.utils.frame_extractor import FrameExtractor

    async def frame(path):
        import asyncio
        from pathlib import Path
        return await asyncio.to_thread(Path(path).read_bytes)

    monkeypatch.setattr(FrameExtractor, 'extract_first_frame', frame)
    monkeypatch.setattr(FrameExtractor, 'extract_last_frame', frame)
    store = _InternalOnlyStore(b'first-video')
    store._objects['videos/s1/v2.mp4'] = b'second-video'
    one = {'objectKey': 'videos/s1/v1.mp4'}
    two = {'objectKey': 'videos/s1/v2.mp4'}
    await extract_cascade_frames(store, one, 's1')
    await extract_cascade_frames(store, two, 's1')
    assert one['lastFrameObjectKey'] != two['lastFrameObjectKey']
    assert store.put[one['lastFrameObjectKey']] == b'first-video'
    assert store.put[two['lastFrameObjectKey']] == b'second-video'


@pytest.mark.asyncio
async def test_frame_extraction_failure_is_reported_not_swallowed(monkeypatch, caplog):
    """A failed extraction must surface in logs while still keeping the asset."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，小雨在公交车里等待姐姐。',
        mode='import_story', duration_sec=30,
    ))
    project_id = created['project']['id']
    record = await pipeline._repository.get(project_id)
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1']}],
        'shots': [{'id': 's1', 'durationSec': 5, 'visualDescription': '公交车驶过雨夜',
                   'characterIds': []}],
        'version': 1,
    }
    record.project['visualAssets'] = []
    await pipeline._repository.save(record)
    pipeline._asset_store = _InternalOnlyStore(_fake_mp4())

    async def boom(path):
        raise RuntimeError('ffmpeg failed: synthetic')

    from comicflow.utils import frame_extractor

    monkeypatch.setattr(frame_extractor.FrameExtractor, 'extract_first_frame', boom)
    monkeypatch.setattr(frame_extractor.FrameExtractor, 'extract_last_frame', boom)

    class Provider(MockDynamicVisualProvider):
        async def generate(self, shot, characters):
            return {
                'id': 'v1', 'shotId': 's1', 'type': 'dynamic', 'mediaType': 'video',
                'objectKey': 'videos/s1/v1.mp4', 'provider': 'test',
            }

    pipeline.set_video_provider(Provider())
    with caplog.at_level('WARNING'):
        result = await pipeline.generate_shot_visual(
            project_id, 's1', expected_version=record.project['version']
        )

    asset = result['asset']
    assert asset['valid'] is False
    assert result['awaitingAdoption'] is True
    assert asset.get('lastFrameObjectKey') is None
    assert asset.get('frameExtractionError')
    assert any('frame' in record.message.lower() for record in caplog.records)
