from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock_media import MockDynamicVisualProvider

STORY = '雨夜，年轻女子走进便利店，向店员询问失踪多年的姐姐。'
CREATE = {'inputType': 'story', 'story': STORY, 'durationSec': 30, 'mode': 'import_story'}


@pytest.fixture
async def context():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        yield runtime, client


async def test_catalog_selection_saved_and_unknown_id_rejected(context):
    runtime, client = context
    catalog = await client.get('/api/visual-styles')
    assert catalog.status_code == 200
    assert len(catalog.json()['items']) == 10
    selected = await client.post('/api/projects', json={**CREATE, 'stylePresetId': 'anime-2d'})
    profile = selected.json()['project']['visualStyleProfile']
    assert profile['presetId'] == 'anime-2d' and profile['revision'] == 2
    pid = selected.json()['project']['id']
    assert (await client.get('/api/projects/' + pid)).json()['project'][
        'visualStyleProfile'] == profile
    before = len(await runtime.pipeline.list_projects())
    bad = await client.post('/api/projects', json={**CREATE, 'stylePresetId': 'unknown'})
    assert bad.status_code == 400
    assert bad.json()['error'] == 'STYLE_PRESET_UNKNOWN'
    assert len(await runtime.pipeline.list_projects()) == before
    legacy = (await client.post('/api/projects', json=CREATE)).json()['project']
    assert legacy.get('visualStyleProfile') is None


async def test_style_reaches_split_character_images_views_scene_and_video(context):
    runtime, client = context
    project = (await client.post('/api/projects', json={
        **CREATE, 'stylePresetId': 'anime-2d'})).json()['project']
    pid = project['id']
    pipeline = runtime.pipeline
    profile = project['visualStyleProfile']
    text_inputs, image_inputs, video_inputs = [], [], []
    original = pipeline._text_provider

    class Text:
        async def split_script(self, story, project_id, target_duration_sec=30):
            text_inputs.append(story)
            return await original.split_script(story, project_id, target_duration_sec)

        async def generate_character_prompt(self, context):
            text_inputs.append(context)
            return {'appearance': '短发年轻女子', 'clothing': '蓝色外套',
                    'personality': '沉稳', 'referenceImagePrompt': '年轻女子的全身参考图'}

    class Image:
        async def generate(self, shot, characters):
            image_inputs.append(deepcopy(shot))
            return {'mediaType': 'image', 'sourceUrl': 'https://offline.invalid/image.png',
                    'provider': 'offline', 'modelVersion': 'chosen-image'}

    class Video(MockDynamicVisualProvider):
        async def generate(self, shot, characters):
            video_inputs.append(deepcopy(shot))
            return {'id': 'v1', 'shotId': shot['id'], 'mediaType': 'video',
                    'sourceUrl': 'https://offline.invalid/video.mp4',
                    'modelVersion': 'chosen-video'}

    pipeline.set_text_provider(Text())
    pipeline.set_reference_image_provider(Image())
    pipeline._dynamic_visual_provider = Video()
    preview = await pipeline.preview_script(pid)
    assert '日系二维动画' in text_inputs[0] and STORY in text_inputs[0]
    record = await pipeline._repository.get(pid)
    record.project['script'] = preview['script']
    await pipeline._repository.save(record)
    card = await pipeline.save_project_character(pid, {
        'name': '小雨', 'appearance': '短发年轻女子', 'clothing': '蓝色外套',
        'personality': '沉稳', 'voice': {'language': 'zh-CN'},
    })
    record = await pipeline._repository.get(pid)
    await pipeline.preview_character_prompt(pid, fields={**card, 'referenceImagePrompt': ''},
        instructions='', character_id=card['id'], expected_version=record.project['version'],
        expected_revision=card.get('revision', 0))
    assert text_inputs[-1]['visualStyleProfile'] == profile
    candidate = await pipeline.generate_character_reference_candidate(
        pid, card['id'], expected_version=record.project['version'])
    approved = await pipeline.approve_character_reference_candidate(
        pid, card['id'], candidate['candidate']['id'],
        expected_version=candidate['projectVersion'])
    assert approved['character']['referenceImageStyleSnapshot'] == profile
    await pipeline.generate_character_reference_views(
        pid, card['id'], expected_version=approved['projectVersion'])
    record = await pipeline._repository.get(pid)
    record.project['script']['scenes'].append({'id': 'style-scene', 'location': '便利店',
                                              'time': '雨夜', 'shotIds': []})
    await pipeline._repository.save(record)
    await pipeline.generate_project_reference(pid, 'scenes', 'style-scene',
                                               expected_version=record.project['version'])
    record = await pipeline._repository.get(pid)
    assert record.project['script']['scenes'][-1]['backgroundImageStyleSnapshot'] == profile
    assert len(image_inputs) == 5  # main, three existing view calls, scene; no extra call
    for request in image_inputs:
        assert request['styleSnapshot'] == profile
        assert '赛璐璐' in request['visualDescription']
        assert '写实电影感' not in request['visualDescription']
        assert '真实织物纤维' not in request['visualDescription']
    record = await pipeline._repository.get(pid)
    shot = record.project['script']['shots'][0]
    shot['characterIds'] = [card['id']]
    await pipeline._repository.save(record)
    original_dialogue = shot.get('dialogue')
    result = await pipeline.generate_shot_visual(pid, shot['id'],
                                                expected_version=record.project['version'])
    assert '日系二维动画' in video_inputs[0]['visualStyle']
    assert video_inputs[0].get('dialogue') == original_dialogue
    assert result['asset']['styleSnapshot'] == profile
    assert result['asset']['modelVersion'] == 'chosen-video'


@pytest.mark.parametrize('preset', ['cinematic-realism', 'guofeng-3d', 'anime-2d',
                                   'guofeng-painted', 'ink-animation', 'graphic-comic'])
async def test_each_preset_uses_frozen_rules_without_mutating_input(preset):
    from comicflow.production.visual_styles import resolve_style
    from comicflow.providers.drama_skills import prepare_visual_asset_request
    profile = resolve_style(preset)
    request = {'imagePurpose': 'character-reference', 'visualDescription': '短发蓝衣女子',
               'styleSnapshot': profile}
    before = deepcopy(request)
    prepared = prepare_visual_asset_request(request)
    assert profile['name'] in prepared['visualDescription']
    assert '短发蓝衣女子' in prepared['visualDescription']
    assert '脸型骨相、眉眼鼻唇' in prepared['visualDescription']
    assert '保留服装层级' in prepared['visualDescription']
    assert request == before
    assert prepared['styleApplication']['engine'] == 'local-style-v1'


async def test_style_survives_database_restart_and_catalog_changes(context, tmp_path):
    from comicflow.infrastructure.database import (
        Base,
        SqlAlchemyProjectRepository,
        create_session_factory,
    )
    from comicflow.production.visual_styles import resolve_style, style_catalog
    runtime, client = context
    project = (await client.post('/api/projects', json={
        **CREATE, 'stylePresetId': 'ink-animation'})).json()['project']
    record = await runtime.pipeline._repository.get(project['id'])
    # A saved v1 project must survive a catalog v2 release and a repository restart.
    record.project['visualStyleProfile']['revision'] = 1
    record.project['visualStyleProfile']['rendering'] = '旧项目保存的水墨笔触，不跟随目录升级。'
    original = deepcopy(record.project['visualStyleProfile'])
    assert resolve_style('ink-animation')['revision'] == 2
    database_url = f'sqlite+aiosqlite:///{tmp_path / "styles.db"}'
    engine, sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await SqlAlchemyProjectRepository(sessions).save(record)
    finally:
        await engine.dispose()
    changed = style_catalog()['items']
    changed[0]['name'] = 'not saved'
    assert resolve_style('cinematic-realism')['name'] == '真人电影写实'
    engine, sessions = create_session_factory(database_url)
    try:
        recreated = create_memory_runtime()
        recreated.pipeline._repository = SqlAlchemyProjectRepository(sessions)
        loaded = await recreated.pipeline.get_snapshot(project['id'])
        assert loaded['project']['visualStyleProfile'] == original
        from comicflow.production.visual_styles import apply_video_style
        prepared = apply_video_style({'id': 's1'}, loaded['project'])
        assert original['rendering'] in prepared['visualStyle']
        assert resolve_style('ink-animation')['rendering'] not in prepared['visualStyle']
    finally:
        await engine.dispose()


def test_frozen_rules_compile_into_both_h3_paths_without_changing_dialogue():
    from comicflow.production.visual_styles import apply_video_style, resolve_style
    from comicflow.providers.h3_context_ir import compile_chinese_intent
    from comicflow.providers.minimax_prompt import build_h3_prompt
    profile = resolve_style('anime-2d')
    profile['rendering'] += '保留项目独有笔触。'
    shot = {'id': 's1', 'durationSec': 5, 'visualDescription': '女子推门入店',
            'dialogue': '你好。', 'visualStyle': '旧漫画默认', 'style': '旧写实默认',
            'scene': {'style': '旧写实默认', 'location': '便利店'}}
    prepared = apply_video_style(shot, {'visualStyleProfile': profile})
    assert '保留项目独有笔触' in prepared['visualStyle']
    assert shot['visualStyle'] == '旧漫画默认'
    assert '日系二维动画' in build_h3_prompt(shot=prepared)
    result = compile_chinese_intent(prepared, [])
    assert '日系二维动画' in result['prompt']
    assert '你好。' in result['prompt']
    assert '旧写实默认' not in result['prompt']


async def test_explicit_scene_generation_uses_project_style(context):
    runtime, client = context
    project = (await client.post('/api/projects', json={
        **CREATE, 'mode': 'guided', 'stylePresetId': 'ink-animation'})).json()['project']
    pipeline = runtime.pipeline
    await pipeline.generate_script(project['id'])
    captured = []

    class Image:
        async def generate(self, shot, characters):
            captured.append(shot)
            return {'mediaType': 'image', 'sourceUrl': 'https://offline.invalid/image.png'}

    pipeline.set_reference_image_provider(Image())
    record = await pipeline._repository.get(project['id'])
    # This contract focuses on scene inputs; no character models participate.
    for shot in record.project['script']['shots']:
        shot['characterIds'] = []
    await pipeline._repository.save(record)
    await pipeline.confirm_script(project['id'], expected_version=record.project['version'])
    assert not captured
    for scene in record.project['script']['scenes']:
        current = await pipeline.get_snapshot(project['id'])
        await pipeline.generate_project_reference(
            project['id'], 'scenes', scene['id'],
            expected_version=current['project']['version'])
    assert captured
    assert all('水墨动画' in request['visualDescription'] for request in captured)
    stored = (await pipeline._repository.get(project['id'])).project
    assert all(scene['backgroundImageStyleSnapshot'] == project['visualStyleProfile']
               for scene in stored['script']['scenes'])


def test_corrupt_profile_does_not_silently_fall_back_to_legacy_rules():
    from comicflow.domain.errors import DomainError
    from comicflow.providers.drama_skills import prepare_visual_asset_request
    with pytest.raises(DomainError, match='STYLE_PROFILE_INVALID'):
        prepare_visual_asset_request({'imagePurpose': 'character-reference',
                                      'visualDescription': '年轻女子', 'styleSnapshot': {}})
