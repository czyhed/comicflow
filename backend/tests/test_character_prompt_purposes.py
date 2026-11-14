"""Purpose-scoped drafts must not rewrite identity or spend hidden image calls."""
import json
from copy import deepcopy

import pytest
from comicflow.production.visual_styles import resolve_style
from comicflow.providers.drama_skills import XIAOLUO_SKILL, load_stage_skill
from test_character_prompt_assistant import (  # reuse the existing public-API fixture
    FIELDS,
    RESULT,
    completion,
    context,
    install_provider,
)

__all__ = ['context']


async def test_image_polish_omits_story_and_returns_only_prompt(context):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        source = json.loads(body['messages'][1]['content'])
        assert source['purpose'] == 'reference-image'
        assert source['outputFields'] == ['referenceImagePrompt']
        assert set(source['fields']) == {'name', 'appearance', 'clothing', 'referenceImagePrompt'}
        assert not {'story', 'shots', 'scriptTitle'} & source.keys()
        assert source['instructions'] == payload['instructions']
        assert 'referenceImagePrompt' in body['messages'][0]['content']
        return completion({'referenceImagePrompt': '蓝色棉布外套，保留织纹和接缝，全身正面。'})

    install_provider(runtime, handler)
    before = deepcopy(await runtime.pipeline._character_repository.get(card['id']))
    result = await client.post(path + '/characters/prompt-preview',
                               json={**payload, 'purpose': 'reference-image'})
    assert result.status_code == 200, result.text
    assert set(result.json()['draft']) == {'name', 'referenceImagePrompt'}
    assert len(calls) == 1
    assert await runtime.pipeline._character_repository.get(card['id']) == before


async def test_settings_returns_selected_fields_with_story_and_no_old_image_prompt(context):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        source = json.loads(body['messages'][1]['content'])
        assert source['purpose'] == 'settings'
        assert source['outputFields'] == ['clothing']
        assert source['story'] and len(source['shots']) == 1
        assert 'referenceImagePrompt' not in source['fields']
        return completion({'clothing': '蓝色棉布外套，袖口有轻微使用痕迹'})

    install_provider(runtime, handler)
    result = await client.post(path + '/characters/prompt-preview', json={
        **payload, 'purpose': 'settings', 'outputFields': ['clothing'],
    })
    assert result.status_code == 200, result.text
    assert set(result.json()['draft']) == {'name', 'clothing'}
    assert len(calls) == 1
    saved = await runtime.pipeline._character_repository.get(card['id'])
    assert saved['appearance'] == FIELDS['appearance']


@pytest.mark.parametrize('bad', [RESULT, {'referenceImagePrompt': ''},
                               {'referenceImagePrompt': 'plastic skin portrait'}])
async def test_scoped_output_rejects_extra_or_bad_fields_without_retry(context, bad):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        calls.append(request)
        return completion(bad)

    install_provider(runtime, handler)
    before = deepcopy(await runtime.pipeline._character_repository.get(card['id']))
    response = await client.post(path + '/characters/prompt-preview',
                                 json={**payload, 'purpose': 'reference-image'})
    assert response.status_code == 502, response.text
    assert response.json()['error'] == 'CHARACTER_PROMPT_INVALID'
    assert len(calls) == 1
    assert await runtime.pipeline._character_repository.get(card['id']) == before


@pytest.mark.parametrize('options', [
    {'purpose': 'settings', 'outputFields': []},
    {'purpose': 'settings', 'outputFields': ['referenceImagePrompt']},
    {'purpose': 'reference-image', 'outputFields': ['appearance']},
    {'purpose': 'settings', 'outputFields': ['clothing', 'clothing']},
])
async def test_invalid_purpose_fields_rejected_before_supplier(context, options):
    runtime, client, path, card, payload = context
    calls = []
    install_provider(runtime, lambda request: calls.append(request) or completion(RESULT))
    response = await client.post(path + '/characters/prompt-preview', json={**payload, **options})
    assert response.status_code == 422
    assert calls == []


async def test_saving_only_polished_prompt_keeps_approved_assets(context):
    runtime, client, path, card, payload = context
    approved = deepcopy(card)
    approved.update(referenceImageObjectKey='approved/main.png',
                    referenceImageUrl='https://offline.invalid/main.png',
                    referenceImageMediaType='image', referenceImageStatus='views-ready',
                    referenceViews=[{'view': 'front', 'objectKey': 'approved/front.png'}],
                    referenceBoard={'objectKey': 'approved/board.jpg'})
    await runtime.pipeline._character_repository.save(approved)
    calls = []
    install_provider(runtime, lambda request: calls.append(request) or completion(RESULT))
    response = await client.patch(path + '/characters/' + card['id'], json={
        **FIELDS, 'referenceImagePrompt': '新提示词：主光柔和，棉布哑光，人物清晰。',
        'voice': card['voice'], 'expectedRevision': 0,
        'expectedVersion': payload['expectedVersion'],
    })
    assert response.status_code == 200, response.text
    saved = response.json()
    for key in ('referenceImageObjectKey', 'referenceImageStatus',
                'referenceViews', 'referenceBoard'):
        assert saved[key] == approved[key]
    assert saved['revision'] == 1
    assert calls == []


def test_prompt_skill_uses_asset_writing_guide_instead_of_poster_examples():
    skill = load_stage_skill(XIAOLUO_SKILL, 'character-prompt')
    assert skill['execution']['files'][-1].endswith('character-prompt-writing.md')
    assert '银色绣花针' not in skill['prompt']
    assert '青黑烟雾背景' not in skill['prompt']
    assert '主图' in skill['prompt'] and '材质' in skill['prompt']


async def test_image_polish_requires_visual_identity_before_text_call(context):
    runtime, client, path, card, payload = context
    calls = []
    install_provider(runtime, lambda request: calls.append(request) or completion(RESULT))
    response = await client.post(path + '/characters/prompt-preview', json={
        **payload, 'purpose': 'reference-image', 'fields': {**FIELDS, 'clothing': ''},
    })
    assert response.status_code == 400
    assert response.json()['error'] == 'CHARACTER_FIELDS_REQUIRED'
    assert calls == []


@pytest.mark.parametrize('preset', [
    'cinematic-realism', 'anime-2d', 'guofeng-3d',
    'guofeng-painted', 'ink-animation', 'graphic-comic',
])
async def test_image_polish_preserves_selected_medium_without_motion_instructions(context, preset):
    runtime, client, path, card, payload = context
    record = await runtime.pipeline._repository.get(path.rsplit('/', 1)[1])
    style = resolve_style(preset)
    record.project['visualStyleProfile'] = style
    await runtime.pipeline._repository.save(record)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        source = json.loads(body['messages'][1]['content'])
        calls.append(source)
        assert source['visualStyle'] == {key: style[key] for key in (
            'name', 'medium', 'rendering', 'lighting', 'avoid')}
        assert source['instructions'] == payload['instructions']
        assert 'visualStyleProfile' not in source and 'shots' not in source
        return completion({
            'referenceImagePrompt': '人物全身正面，轮廓清晰，服装材质与所选画风一致。'})

    install_provider(runtime, handler)
    response = await client.post(path + '/characters/prompt-preview', json={
        **payload, 'purpose': 'reference-image',
    })
    assert response.status_code == 200, response.text
    assert len(calls) == 1
