import json
from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider

FIELDS = {
    "name": "小雨", "appearance": "黑色短发", "clothing": "蓝色外套", "personality": "沉稳",
    "referenceImagePrompt": "漫画风格，黑色短发的年轻女子穿蓝色外套，全身正面，纯色背景。",
}
RESULT = {key: value for key, value in FIELDS.items() if key != "name"}


@pytest.fixture
async def context():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        created = (await client.post('/api/projects', json={
            'inputType': 'story', 'story': '雨夜，小雨在车站等车，遇到故人。',
            'durationSec': 30, 'mode': 'import_story',
        })).json()
        path = '/api/projects/' + created['project']['id']
        card = (await client.post(path + '/characters', json={
            **FIELDS, 'voice': {'language': 'zh-CN'},
        })).json()
        record = await runtime.pipeline._repository.get(created['project']['id'])
        record.project['script'] = {'title': '雨夜', 'scenes': [], 'shots': [
            {'id': 's1', 'characterIds': [card['id']], 'visualDescription': '小雨冒雨走向车站'},
            {'id': 's2', 'characterIds': [], 'visualDescription': '其他角色的独立场景'},
        ]}
        await runtime.pipeline._repository.save(record)
        payload = {
            'expectedVersion': record.project['version'], 'characterId': card['id'],
            'expectedRevision': card.get('revision', 0), 'fields': FIELDS,
            'instructions': '保持蓝色外套，增加清晰的衣服材质。',
        }
        yield runtime, client, path, card, payload


def install_provider(runtime, handler):
    runtime.pipeline.set_text_provider(BailianTextProvider(
        api_key='offline', base_url='https://text.test/v1', model='chosen-model',
        max_retries=3, transport=httpx.MockTransport(handler),
    ))


def completion(value):
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(value)}}]})


async def test_preview_is_read_only_and_saved_prompt_reaches_image_provider(context):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['model'] == 'chosen-model'
        assert '简体中文' in body['messages'][0]['content']
        source = json.loads(body['messages'][1]['content'])
        assert source['fields'] == FIELDS
        assert source['shots'][0]['visualDescription'] == '小雨冒雨走向车站'
        assert len(source['shots']) == 1
        return completion(RESULT)

    install_provider(runtime, handler)
    before = await runtime.pipeline._character_repository.get(card['id'])
    project_before = (await client.get(path)).json()
    response = await client.post(path + '/characters/prompt-preview', json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['draft'] == FIELDS
    assert await runtime.pipeline._character_repository.get(card['id']) == before
    assert (await client.get(path)).json() == project_before
    exact = {**preview['draft'],
             'referenceImagePrompt': '用户修改：漫画风格，蓝色棉布外套，全身正面。'}
    saved = await client.patch(path + '/characters/' + card['id'], json={
        **exact, 'voice': card['voice'], 'expectedRevision': preview['expectedRevision'],
    })
    assert saved.status_code == 200
    assert saved.json()['referenceImagePrompt'] == exact['referenceImagePrompt']
    assert saved.json()['revision'] == 1
    assert len(calls) == 1
    images = []

    class Image:
        async def generate(self, shot, characters):
            images.append(shot)
            return {'mediaType': 'image', 'sourceUrl': 'https://asset.test/reference.png'}

    runtime.pipeline.set_reference_image_provider(Image())
    generated = await client.post(path + '/references/characters/' + card['id'], json={
        'expectedVersion': payload['expectedVersion'],
    })
    assert generated.status_code == 200, generated.text
    assert exact['referenceImagePrompt'] in images[0]['visualDescription']
    persisted = (await client.get(path + '/characters')).json()[0]
    assert persisted['referenceImageMediaType'] == 'image'
    changed = await client.patch(path + '/characters/' + card['id'], json={
        **exact, 'referenceImagePrompt': '漫画风格，正面全身，清晰五官，白色背景。',
        'voice': card['voice'], 'expectedRevision': 1,
    })
    assert changed.status_code == 200
    # A prompt draft affects the next generation, not an already confirmed image.
    assert changed.json()['referenceImageUrl'] == persisted['referenceImageUrl']
    assert (await client.patch(path + '/characters/' + card['id'], json={
        **exact, 'voice': card['voice'], 'expectedRevision': 1,
    })).status_code == 409


@pytest.mark.parametrize('bad', [
    {**RESULT, 'appearance': 'A young woman wearing a blue coat'},
    {**RESULT, 'appearance': '错误\ufffd文字'},
    {**RESULT, 'referenceImagePrompt': r'中文\u4e2d'},
    {**RESULT, 'clothing': []}, {**RESULT, 'referenceImagePrompt': ''},
    {**RESULT, 'extra': '字段'},
])
async def test_invalid_preview_preserves_card_and_does_not_retry(context, bad):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        calls.append(request)
        return completion(bad)

    install_provider(runtime, handler)
    before = await runtime.pipeline._character_repository.get(card['id'])
    response = await client.post(path + '/characters/prompt-preview', json=payload)
    assert response.status_code == 502
    assert response.json()['error'] == 'CHARACTER_PROMPT_INVALID'
    assert len(calls) == 1
    assert await runtime.pipeline._character_repository.get(card['id']) == before


async def test_preflight_checks_and_provider_failure(context):
    runtime, client, path, card, payload = context
    assert (await client.post(path + '/characters/prompt-preview', json=payload)).status_code == 409
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    install_provider(runtime, handler)
    for patch, status in [({'expectedVersion': -1}, 409), ({'expectedRevision': 9}, 409),
                          ({'characterId': 'missing'}, 404)]:
        response = await client.post(path + '/characters/prompt-preview', json={**payload, **patch})
        assert response.status_code == status
    assert calls == []
    failed = await client.post(path + '/characters/prompt-preview', json=payload)
    assert failed.status_code == 503
    assert len(calls) == 1


async def test_new_character_preview_does_not_create_card(context):
    runtime, client, path, card, payload = context
    install_provider(runtime, lambda request: completion(RESULT))
    before = deepcopy(await runtime.pipeline._character_repository.list())
    payload.pop('characterId')
    payload.pop('expectedRevision')
    payload['fields'] = {'name': '新角色'}
    response = await client.post(path + '/characters/prompt-preview', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['draft']['name'] == '新角色'
    assert await runtime.pipeline._character_repository.list() == before


async def test_character_prompt_receives_saved_generated_story(context):
    runtime, client, path, card, payload = context
    record = await runtime.pipeline._repository.get(path.rsplit('/', 1)[1])
    record.project['generatedStoryText'] = '完整故事：小雨是一名维修工，穿着蓝色工作外套。'
    await runtime.pipeline._repository.save(record)

    def handler(request):
        body = json.loads(request.content)
        source = json.loads(body['messages'][1]['content'])
        assert source['story'] == record.project['generatedStoryText']
        return completion(RESULT)

    install_provider(runtime, handler)
    response = await client.post(path + '/characters/prompt-preview', json=payload)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('failure', ['timeout', 'rejected'])
async def test_character_error_preserves_safe_stage_and_never_retries(context, failure):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        calls.append(request)
        if failure == 'timeout':
            raise httpx.ReadTimeout('private-secret', request=request)
        return httpx.Response(400, json={'error': {
            'code': 'InvalidParameter', 'param': 'response_format', 'message': 'private-secret',
        }})

    install_provider(runtime, handler)
    before = deepcopy((await client.get(path)).json())
    card_before = deepcopy(await runtime.pipeline._character_repository.get(card['id']))
    response = await client.post(path + '/characters/prompt-preview', json=payload)
    assert len(calls) == 1
    assert 'private-secret' not in response.text
    assert (await client.get(path)).json() == before
    assert await runtime.pipeline._character_repository.get(card['id']) == card_before
    assert response.status_code == (504 if failure == 'timeout' else 400)
    assert response.json()['stage'] == 'character_prompt'
    if failure == 'timeout':
        assert response.json()['timeoutPhase'] == 'read'
        assert response.json()['timeoutMs'] > 0
    else:
        assert response.json()['parameter'] == 'response_format'


async def test_project_access_and_foreign_character_rejected_before_text_call(context):
    runtime, client, path, card, payload = context
    calls = []

    def handler(request):
        calls.append(request)
        return completion(RESULT)

    install_provider(runtime, handler)
    foreign = deepcopy(card)
    foreign.update({'id': 'foreign', 'projectId': 'other-project'})
    await runtime.pipeline._character_repository.save(foreign)
    response = await client.post(path + '/characters/prompt-preview',
                                 json={**payload, 'characterId': 'foreign'})
    assert response.status_code == 403
    record = await runtime.pipeline._repository.get(path.rsplit('/', 1)[1])
    record.project['ownerUserId'] = 'owner'
    await runtime.pipeline._repository.save(record)
    denied = await client.post(path + '/characters/prompt-preview', json=payload)
    assert denied.status_code == 403
    assert calls == []


@pytest.mark.parametrize('changed', ['character', 'script'])
async def test_context_changed_during_text_call_rejects_preview(context, changed):
    runtime, client, path, card, payload = context

    async def handler(request):
        if changed == 'character':
            current = await runtime.pipeline._character_repository.get(card['id'])
            current.update({'revision': 1, 'appearance': '其他窗口更新的长发'})
            await runtime.pipeline._character_repository.save(current)
        else:
            record = await runtime.pipeline._repository.get(path.rsplit('/', 1)[1])
            record.project['version'] += 1
            await runtime.pipeline._repository.save(record)
        return completion(RESULT)

    install_provider(runtime, handler)
    response = await client.post(path + '/characters/prompt-preview', json=payload)
    assert response.status_code == 409
    assert response.json()['error'] == (
        'CHARACTER_VERSION_CONFLICT' if changed == 'character' else 'VERSION_CONFLICT'
    )
    stale_save = await client.patch(path + '/characters/' + card['id'], json={
        **FIELDS, 'voice': card['voice'], 'expectedRevision': 0,
        'expectedVersion': payload['expectedVersion'],
    })
    assert stale_save.status_code == 409


async def test_prompt_changed_during_image_generation_does_not_restore_old_reference(context):
    runtime, client, path, card, payload = context

    class Image:
        async def generate(self, shot, characters):
            saved = await client.patch(path + '/characters/' + card['id'], json={
                **FIELDS, 'referenceImagePrompt': '新的角色提示词，全身正面，白色背景。',
                'voice': card['voice'], 'expectedRevision': 0,
            })
            assert saved.status_code == 200
            return {'mediaType': 'image', 'sourceUrl': 'https://asset.test/old.png'}

    runtime.pipeline.set_reference_image_provider(Image())
    response = await client.post(path + '/references/characters/' + card['id'], json={
        'expectedVersion': payload['expectedVersion'],
    })
    assert response.status_code == 409
    current = await runtime.pipeline._character_repository.get(card['id'])
    assert current['referenceImagePrompt'] == '新的角色提示词，全身正面，白色背景。'
    assert 'referenceImageUrl' not in current
