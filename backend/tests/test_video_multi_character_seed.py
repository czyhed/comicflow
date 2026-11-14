import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider


class _Store:
    """Asset store stub exposing only the internal read paths."""

    def __init__(self) -> None:
        self.put: dict[str, bytes] = {}

    async def presigned_get_url(self, key, expires_in=900):
        return f'https://assets.test/{key}'

    async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
        return b'\x89PNG\r\n\x1a\n' + key.encode()

    async def put_bytes(self, key, content, content_type):
        self.put[key] = content
        return key


async def _project_with_two_characters(pipeline):
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，小雨与姐姐在公交车站相遇。',
        mode='import_story', duration_sec=30,
    ))
    project_id = created['project']['id']
    record = await pipeline._repository.get(project_id)
    for char_id, name in (('c1', '小雨'), ('c2', '姐姐')):
        await pipeline._character_repository.save({
            'id': char_id, 'name': name, 'appearance': '短发', 'clothing': '蓝色外套',
            'personality': '沉稳', 'voice': {},
            'referenceImageObjectKey': f'characters/{char_id}.png',
        })
    return project_id, record


@pytest.mark.asyncio
async def test_multi_character_scene_first_shot_falls_back_to_scene_background():
    """A multi-character shot opening a scene must still receive a first frame."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    project_id, record = await _project_with_two_characters(pipeline)
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1'],
                    'backgroundImageObjectKey': 'backgrounds/scene.png'}],
        'shots': [
            {'id': 's1', 'durationSec': 5, 'visualDescription': '两人在雨中对视',
             'characterIds': ['c1', 'c2']},
        ],
        'version': 1,
    }
    record.project['visualAssets'] = []
    await pipeline._repository.save(record)
    pipeline._asset_store = _Store()
    captured: dict = {}

    class Provider(BailianImageToVideoProvider):
        def __init__(self):
            super().__init__(api_key='offline', model='wan2.7-i2v', resolution='720P')

        async def generate(self, shot, characters, **kwargs):
            captured.update(shot)
            raise RuntimeError('VIDEO_FIRST_FRAME_UNREADABLE')

    pipeline.set_video_provider(Provider())
    with pytest.raises(Exception, match='VIDEO_FIRST_FRAME_UNREADABLE'):
        await pipeline.generate_shot_visual(
            project_id, 's1', expected_version=record.project['version']
        )
    assert captured['firstFrameObjectKey'] == 'backgrounds/scene.png'


@pytest.mark.asyncio
async def test_multi_character_shot_without_tail_frame_uses_scene_background():
    """Missing previous tail frame must fall back instead of raising CASCADE_FRAME_MISSING."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    project_id, record = await _project_with_two_characters(pipeline)
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1', 's2'],
                    'backgroundImageObjectKey': 'backgrounds/scene.png'}],
        'shots': [
            {'id': 's1', 'durationSec': 5, 'visualDescription': '公交车驶过雨夜',
             'characterIds': ['c1']},
            {'id': 's2', 'durationSec': 6, 'visualDescription': '两人并肩走出车站',
             'characterIds': ['c1', 'c2']},
        ],
        'version': 1,
    }
    # Previous shot produced a real video but frame extraction never stored a tail frame.
    record.project['visualAssets'] = [{
        'id': 'v1', 'shotId': 's1', 'mediaType': 'video', 'valid': True,
        'objectKey': 'videos/s1/v1.mp4',
    }]
    await pipeline._repository.save(record)
    pipeline._asset_store = _Store()
    captured: dict = {}

    class Provider(BailianImageToVideoProvider):
        def __init__(self):
            super().__init__(api_key='offline', model='wan2.7-i2v', resolution='720P')

        async def generate(self, shot, characters, **kwargs):
            captured.update(shot)
            raise RuntimeError('VIDEO_FIRST_FRAME_UNREADABLE')

    pipeline.set_video_provider(Provider())
    with pytest.raises(Exception, match='VIDEO_FIRST_FRAME_UNREADABLE'):
        await pipeline.generate_shot_visual(
            project_id, 's2', expected_version=record.project['version']
        )
    assert captured['firstFrameObjectKey'] == 'backgrounds/scene.png'


@pytest.mark.asyncio
async def test_available_tail_frame_still_preferred_for_multi_character_shot():
    """When a real tail frame exists, cascade continuity wins over the scene background."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    project_id, record = await _project_with_two_characters(pipeline)
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1', 's2'],
                    'backgroundImageObjectKey': 'backgrounds/scene.png'}],
        'shots': [
            {'id': 's1', 'durationSec': 5, 'visualDescription': '公交车驶过雨夜',
             'characterIds': ['c1']},
            {'id': 's2', 'durationSec': 6, 'visualDescription': '两人并肩走出车站',
             'characterIds': ['c1', 'c2']},
        ],
        'version': 1,
    }
    record.project['visualAssets'] = [{
        'id': 'v1', 'shotId': 's1', 'mediaType': 'video', 'valid': True,
        'objectKey': 'videos/s1/v1.mp4',
        'lastFrameObjectKey': 'visuals/s1/last_frame.jpg',
    }]
    await pipeline._repository.save(record)
    pipeline._asset_store = _Store()
    captured: dict = {}

    class Provider(BailianImageToVideoProvider):
        def __init__(self):
            super().__init__(api_key='offline', model='wan2.7-i2v', resolution='720P')

        async def generate(self, shot, characters, **kwargs):
            captured.update(shot)
            raise RuntimeError('VIDEO_FIRST_FRAME_UNREADABLE')

    pipeline.set_video_provider(Provider())
    with pytest.raises(Exception, match='VIDEO_FIRST_FRAME_UNREADABLE'):
        await pipeline.generate_shot_visual(
            project_id, 's2', expected_version=record.project['version']
        )
    assert captured['firstFrameObjectKey'] == 'visuals/s1/last_frame.jpg'


@pytest.mark.asyncio
async def test_multi_character_shot_without_any_seed_is_rejected_clearly():
    """No character reference, no background, no tail frame must fail explicitly."""
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，两位陌生人在车站相遇。',
        mode='import_story', duration_sec=30,
    ))
    project_id = created['project']['id']
    record = await pipeline._repository.get(project_id)
    for char_id, name in (('c1', '小雨'), ('c2', '姐姐')):
        await pipeline._character_repository.save({
            'id': char_id, 'name': name, 'appearance': '短发', 'clothing': '蓝色外套',
            'personality': '沉稳', 'voice': {},
        })
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1']}],
        'shots': [
            {'id': 's1', 'durationSec': 5, 'visualDescription': '两人在雨中对视',
             'characterIds': ['c1', 'c2']},
        ],
        'version': 1,
    }
    record.project['visualAssets'] = []
    await pipeline._repository.save(record)
    pipeline._asset_store = _Store()

    class Provider(BailianImageToVideoProvider):
        def __init__(self):
            super().__init__(api_key='offline', model='wan2.7-i2v', resolution='720P')

    pipeline.set_video_provider(Provider())
    with pytest.raises(Exception, match='VIDEO_FIRST_FRAME_REQUIRED'):
        await pipeline.generate_shot_visual(
            project_id, 's1', expected_version=record.project['version']
        )
