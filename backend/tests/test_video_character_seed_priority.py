import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider


@pytest.mark.asyncio
async def test_single_character_seed_is_used_before_previous_video_tail_cascade():
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，小雨在公交车里等待姐姐。',
        mode='import_story', duration_sec=30,
    ))
    project_id = created['project']['id']
    record = await pipeline._repository.get(project_id)
    await pipeline._character_repository.save({
        'id': 'c1', 'name': '小雨', 'appearance': '短发', 'clothing': '蓝色外套',
        'personality': '沉稳', 'voice': {}, 'referenceImageObjectKey': 'characters/c1.png',
    })
    record.project['script'] = {
        'scenes': [{'id': 'scene1', 'shotIds': ['s1', 's2'],
                    'backgroundImageObjectKey': 'backgrounds/scene.png'}],
        'shots': [
            {'id': 's1', 'durationSec': 5, 'visualDescription': '公交车驶过雨夜',
             'characterIds': []},
            {'id': 's2', 'durationSec': 4, 'visualDescription': '小雨低头看手机',
             'characterIds': ['c1']},
        ],
        'version': 1,
    }
    record.project['visualAssets'] = [{
        'id': 'v1', 'shotId': 's1', 'mediaType': 'video', 'valid': True,
        'objectKey': 'videos/s1/v1.mp4',
    }]
    await pipeline._repository.save(record)
    class Store:
        async def presigned_get_url(self, key, expires_in=900):
            return f'https://assets.test/{key}'

    pipeline._asset_store = Store()
    captured = {}

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
    assert captured['firstFrameObjectKey'] == 'characters/c1.png'
