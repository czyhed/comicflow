"""Public-entry characterization captured before the character module extraction."""
from __future__ import annotations

import io
import json
from copy import deepcopy
from pathlib import Path

import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from PIL import Image


@pytest.fixture
async def character_flow():
    runtime = create_memory_runtime()
    p = runtime.pipeline
    created = await p.create_project(CreateProject(
        input_type='story', story='雨夜，小雨穿着蓝色外套在车站等候朋友。',
        duration_sec=30, mode='import_story'))
    pid = created['project']['id']
    card = await p.save_project_character(pid, {
        'name': '小雨', 'appearance': '黑色短发，清晰五官', 'clothing': '蓝色棉布外套',
        'personality': '沉静', 'referenceImagePrompt': '写实电影感，单人全身，纯色背景。',
        'voice': {'language': 'zh-CN'},
    })
    output = io.BytesIO()
    Image.new('RGB', (64, 96), 'navy').save(output, 'PNG')
    objects = {}
    calls = []

    class Store:
        async def put_bytes(self, key, content, content_type):
            objects[key] = content
            return key

        async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
            return objects[key]

        async def presigned_get_url(self, key, expires_in=900):
            return f'https://offline.invalid/{key}'

    class Images:
        fail_at = None

        async def generate(self, shot, characters):
            calls.append({'shot': deepcopy(shot), 'characters': deepcopy(characters)})
            if len(calls) == self.fail_at:
                raise RuntimeError('PROVIDER_TIMEOUT')
            key = f'images/{len(calls)}.png'
            objects[key] = output.getvalue()
            return {'id': f'image-{len(calls)}', 'mediaType': 'image', 'objectKey': key,
                    'provider': 'offline-images', 'modelVersion': 'fixture-v1'}

    images = Images()
    p._asset_store = Store()
    p.set_reference_image_provider(images)
    return p, pid, card, calls, images, objects


async def approve_main(p, pid, card):
    version = (await p.get_snapshot(pid))['project']['version']
    candidate = await p.generate_character_reference_candidate(
        pid, card['id'], expected_version=version)
    approved = await p.approve_character_reference_candidate(
        pid, card['id'], candidate['candidate']['id'],
        expected_version=candidate['projectVersion'])
    return candidate, approved


async def test_requests_board_reuse_and_video_inputs_match_pre_split_contract(character_flow):
    p, pid, card, calls, _, objects = character_flow
    candidate, approved = await approve_main(p, pid, card)
    assert candidate['projectVersion'] + 1 == approved['projectVersion']
    views = await p.generate_character_reference_views(
        pid, card['id'], expected_version=approved['projectVersion'])
    assert len(calls) == 4
    assert [v['view'] for v in views['views']] == ['front', 'three-quarter', 'profile']
    board = views['character']['referenceBoard']
    assert board['layout'] == ['main', 'front', 'three-quarter', 'profile']
    assert board['columns'] == 2
    assert Image.open(io.BytesIO(objects[board['objectKey']])).size == (1536, 1536)
    assert board['sourceObjectKeys'] == [f'images/{i}.png' for i in range(1, 5)]
    assert views['projectVersion'] == approved['projectVersion'] + 4
    reused = await p.generate_character_reference_views(
        pid, card['id'], expected_version=views['projectVersion'])
    assert reused['reused'] and reused['projectVersion'] == views['projectVersion']
    assert len(calls) == 4
    record = await p._repository.get(pid)
    record.project['script'] = {'shots': [{'id': 's1', 'characterIds': [card['id']]}]}
    await p._repository.save(record)
    inputs = await p.get_shot_character_input(pid, 's1')
    assert inputs[0]['referenceImageObjectKey'] == 'images/1.png'
    assert inputs[0]['referenceBoardObjectKey'] == board['objectKey']
    # Freeze actual requests; preserve the original extraction baseline separately.
    normalized = deepcopy(calls)
    for item in normalized:
        item['shot']['id'] = '<operation-id>'
    fixtures = Path(__file__).parent / 'fixtures'
    expected = json.loads((fixtures / 'character-requests-quality-contract.json').read_text(
        encoding='utf-8'))
    original = json.loads((fixtures / 'character-requests-before-split.json').read_text(
        encoding='utf-8'))
    # Only reviewed material prose and its source hash may differ; input images,
    # request fields and call order must still match the pre-extraction baseline.
    from comicflow.providers.drama_skills import XIAOLUO_SKILL, load_stage_skill
    for actual, baseline in zip(normalized, expected, strict=True):
        execution = actual['shot']['skillExecution']
        current = load_stage_skill(XIAOLUO_SKILL, execution['task'])['execution']
        assert execution == current
        baseline['shot']['skillExecution']['sha256'] = current['sha256']
    assert normalized == expected
    for actual, baseline in zip(deepcopy(normalized), original, strict=True):
        actual['shot']['visualDescription'] = baseline['shot']['visualDescription']
        actual['shot']['skillExecution']['sha256'] = baseline['shot']['skillExecution']['sha256']
        assert actual == baseline


async def test_partial_views_keep_saved_front_without_automatic_retry(character_flow):
    p, pid, card, calls, images, _ = character_flow
    _, approved = await approve_main(p, pid, card)
    images.fail_at = 3
    with pytest.raises(DomainError, match='REFERENCE_VIEWS_PARTIAL') as failure:
        await p.generate_character_reference_views(
            pid, card['id'], expected_version=approved['projectVersion'])
    assert failure.value.detail['generatedViews'] == ['front']
    assert failure.value.detail['jobId'].startswith('ijob_')
    assert len(calls) == 3
    saved = (await p.list_project_characters(pid))[0]
    assert saved['referenceImageStatus'] == 'views-partial'
    assert saved['referenceImageObjectKey'] == 'images/1.png'
    assert [v['view'] for v in saved['referenceViews']] == ['front']
    assert not saved.get('referenceBoard')
    assert (await p.get_snapshot(pid))['project']['version'] == approved['projectVersion'] + 1


async def test_candidate_edit_conflict_and_foreign_project_do_not_install_image(character_flow):
    p, pid, card, calls, images, _ = character_flow
    original = images.generate

    async def edit_during_request(shot, characters):
        result = await original(shot, characters)
        await p.save_project_character(pid, {**card, 'clothing': '白色衬衫'},
                                       character_id=card['id'])
        return result

    images.generate = edit_during_request
    version = (await p.get_snapshot(pid))['project']['version']
    with pytest.raises(DomainError, match='CHARACTER_VERSION_CONFLICT'):
        await p.generate_character_reference_candidate(pid, card['id'], expected_version=version)
    assert len(calls) == 1
    saved = (await p.list_project_characters(pid))[0]
    assert saved['clothing'] == '白色衬衫' and not saved.get('referenceImageCandidate')
    other = await p.create_project(CreateProject(
        input_type='story', story='另一位年轻人在另一座车站等待家人。',
        duration_sec=30, mode='import_story'))
    with pytest.raises(DomainError, match='CHARACTER_ACCESS_DENIED'):
        await p.generate_character_reference_candidate(
            other['project']['id'], card['id'], expected_version=other['project']['version'])
    assert len(calls) == 1


async def ready_board(flow):
    p, pid, card, *_ = flow
    _, approved = await approve_main(p, pid, card)
    result = await p.generate_character_reference_views(
        pid, card['id'], expected_version=approved['projectVersion'])
    record = await p._repository.get(pid)
    record.project['script'] = {'shots': [{'id': 's1', 'characterIds': [card['id']]}]}
    await p._repository.save(record)
    return result['character']


async def test_main_replacement_keeps_old_board_but_video_uses_new_main(character_flow):
    p, pid, card, calls, _, objects = character_flow
    old = await ready_board(character_flow)
    old_board = deepcopy(old['referenceBoard'])
    old_bytes = objects[old_board['objectKey']]
    version = (await p.get_snapshot(pid))['project']['version']
    candidate = await p.generate_character_reference_candidate(
        pid, card['id'], expected_version=version)
    # Creating a candidate does not replace the current confirmed board.
    inputs = await p.get_shot_character_input(pid, 's1')
    assert inputs[0]['referenceBoardObjectKey'] == old_board['objectKey']
    approved = await p.approve_character_reference_candidate(
        pid, card['id'], candidate['candidate']['id'],
        expected_version=candidate['projectVersion'])
    saved = approved['character']
    assert saved['referenceBoard']['status'] == 'stale'
    assert saved['referenceBoard']['objectKey'] == old_board['objectKey']
    inputs = await p.get_shot_character_input(pid, 's1')
    assert 'referenceBoardObjectKey' not in inputs[0]
    assert 'referenceViews' not in inputs[0]
    assert inputs[0]['referenceImageObjectKey'] == candidate['candidate']['objectKey']
    assert len(calls) == 5
    new = await p.generate_character_reference_views(
        pid, card['id'], expected_version=approved['projectVersion'])
    assert new['character']['referenceBoard']['objectKey'] != old_board['objectKey']
    assert objects[old_board['objectKey']] == old_bytes
    assert len(calls) == 8  # No extra text or image requests introduced by validity checks.


@pytest.mark.parametrize('field', ['appearance', 'clothing'])
@pytest.mark.parametrize('entry', ['project', 'direct'])
async def test_visual_edit_invalidates_reference_assets_in_both_entrypoints(
    character_flow, field, entry,
):
    from comicflow.domain.models import Actor
    p, pid, card, calls, *_ = character_flow
    old = await ready_board(character_flow)
    changed = {**old, field: '新的角色外观' if field == 'appearance' else '白色衬衫'}
    if entry == 'project':
        result = await p.save_project_character(pid, changed, character_id=card['id'])
    else:
        record = await p._repository.get(pid)
        result = await p.update_character(
            card['id'], changed, actor=Actor.guest(record.guest_session['id']))
    assert result['referenceBoard']['status'] == 'stale'
    assert result['referenceBoard']['objectKey'] == old['referenceBoard']['objectKey']
    inputs = await p.get_shot_character_input(pid, 's1')
    assert not any(k in inputs[0] for k in (
        'referenceImageUrl', 'referenceBoardUrl', 'referenceViews'))
    assert len(calls) == 4


@pytest.mark.parametrize('change', ['source-key', 'source-version', 'view-source'])
async def test_video_checks_stored_provenance_without_trusting_board_presence(
    character_flow, change,
):
    p, pid, card, calls, *_ = character_flow
    saved = await ready_board(character_flow)
    if change == 'source-key':
        # Historical board has no new version field; original main object is still known.
        saved['referenceBoard'].pop('sourceImageVersion', None)
        saved['referenceImageObjectKey'] = 'different/main.png'
    elif change == 'source-version':
        # Same storage key alone must not validate a board for another adopted image.
        saved['referenceBoard']['sourceImageVersion'] = 'previous-adoption'
    else:
        saved['referenceViews'][0]['objectKey'] = 'different/front.png'
    await p._character_repository.save(saved)
    inputs = await p.get_shot_character_input(pid, 's1')
    assert 'referenceBoardObjectKey' not in inputs[0]
    assert inputs[0]['referenceImageObjectKey'] == saved['referenceImageObjectKey']
    if change == 'source-key':
        assert 'referenceViews' not in inputs[0]
    assert len(calls) == 4


async def test_prompt_only_edit_keeps_current_board_and_source_version(character_flow):
    p, pid, card, calls, *_ = character_flow
    saved = await ready_board(character_flow)
    result = await p.save_project_character(
        pid, {**saved, 'referenceImagePrompt': '仅修改下次生图用的文字'}, character_id=card['id'])
    assert result['referenceBoard'] == saved['referenceBoard']
    inputs = await p.get_shot_character_input(pid, 's1')
    assert inputs[0]['referenceBoardObjectKey'] == saved['referenceBoard']['objectKey']
    assert len(calls) == 4


async def test_edit_while_composing_board_does_not_restore_old_character(character_flow):
    p, pid, card, calls, _, _ = character_flow
    _, approved = await approve_main(p, pid, card)
    original = p._asset_store.get_bytes
    edited = False

    async def edit_during_composition(key, max_bytes=20 * 1024 * 1024):
        nonlocal edited
        if not edited:
            edited = True
            await p.save_project_character(
                pid, {**card, 'clothing': '白色衬衫'}, character_id=card['id'])
        return await original(key, max_bytes)

    p._asset_store.get_bytes = edit_during_composition
    with pytest.raises(DomainError, match='CHARACTER_VERSION_CONFLICT'):
        await p.generate_character_reference_views(
            pid, card['id'], expected_version=approved['projectVersion'])
    saved = (await p.list_project_characters(pid))[0]
    assert saved['clothing'] == '白色衬衫'
    assert not saved.get('referenceImageObjectKey')
    assert not saved.get('referenceBoard')
    assert len(calls) == 4
