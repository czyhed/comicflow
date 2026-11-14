"""Single edit submission, explicit board adoption and safe recovery; no network."""
import base64
import io
import json
from copy import deepcopy

import httpx
import pytest
import test_durable_image_jobs as fixtures
from comicflow.domain.errors import DomainError
from comicflow.production.reference_images import reference_asset_is_current
from comicflow.production.visual_styles import resolve_style
from PIL import Image

images = fixtures.images
sql_images = fixtures.sql_images


async def prepare_board(data):
    p, pid, card, version, calls, control = data
    main = await p.generate_character_reference_candidate(pid, card['id'], expected_version=version)
    approved = await p.approve_character_reference_candidate(
        pid, card['id'], main['candidate']['id'], expected_version=main['projectVersion'])
    original = p._reference_image_provider._transport
    bodies = []
    output = io.BytesIO()
    Image.new('RGB', (768, 512), 'blue').save(output, 'PNG')

    async def handler(req):
        if req.method == 'POST':
            bodies.append(json.loads(req.content))
        result = await original.handle_async_request(req)
        if req.url.path.endswith('/result.png'):
            return httpx.Response(200, content=control.get('board_bytes', output.getvalue()))
        return result

    provider = p._reference_image_provider
    provider._model, provider._size = 'wan2.6-image', '1536*1024'
    provider._transport = httpx.MockTransport(handler)
    return approved, bodies


async def queue(data, operation='board'):
    p, pid, card, *_ = data
    return await p.request_image_job(pid, card['id'],
        expected_version=(await p.get_snapshot(pid))['project']['version'],
        operation_id=operation, purpose='board')


async def adopt(data, candidate, version=None):
    p, pid, card, *_ = data
    return await p.approve_character_reference_board(pid, card['id'], candidate['id'],
        expected_version=version if version is not None else
        (await p.get_snapshot(pid))['project']['version'])


async def test_board_one_edit_preserves_old_until_explicit_atomic_approval(sql_images):
    data, _ = sql_images
    p, pid, card, _, calls, _ = data
    approved, bodies = await prepare_board(data)
    current = approved['character']
    old = {'id': 'old', 'status': 'approved', 'url': 'https://offline.invalid/old.png'}
    current['referenceBoard'] = deepcopy(old)
    await p._character_repository.save(current)
    job = await queue(data)
    done = await p.run_image_job(job['id'])
    assert done['status'] == 'succeeded', done
    assert done['callsStarted'] == 1 and len(bodies) == 1 and calls.count('submit') == 2
    source = bodies[0]['input']['messages'][0]['content'][1]['image']
    main_bytes = await p._asset_store.get_bytes(current['referenceImageObjectKey'])
    assert base64.b64decode(source.split(',')[1]) == main_bytes
    prompt = bodies[0]['input']['messages'][0]['content'][0]['text']
    assert '正面' in prompt and '严格侧面' in prompt and '背面' in prompt
    assert '9:16' not in prompt and '单一人物、全身、正面' not in prompt
    assert bodies[0]['parameters']['n'] == 1
    assert bodies[0]['parameters']['size'] == '1536*1024'
    saved = await p._character_repository.get(card['id'])
    candidate = saved['referenceBoardCandidate']
    assert saved['referenceBoard'] == old
    assert not reference_asset_is_current(saved, candidate)
    assert candidate['width'] == 768 and candidate['height'] == 512
    assert candidate['skillExecution']['task'] == 'character-board'
    version = (await p.get_snapshot(pid))['project']['version']
    result = await adopt(data, candidate)
    assert result['character']['referenceBoard']['id'] == candidate['id']
    assert result['character']['referenceBoardCandidate'] is None
    assert reference_asset_is_current(result['character'], result['character']['referenceBoard'])
    assert (await adopt(data, candidate, version))['projectVersion'] == version + 1
    assert calls.count('submit') == 2


async def test_board_requires_approved_source_and_edit_capability(images):
    with pytest.raises(DomainError, match='REFERENCE_IMAGE_NOT_APPROVED'):
        await queue(images)
    await prepare_board(images)
    p = images[0]
    p._reference_image_provider._model = 'wan2.2-t2i-flash'
    with pytest.raises(DomainError, match='IMAGE_EDIT_UNSUPPORTED'):
        await queue(images)
    assert images[4].count('submit') == 1


async def test_board_recovery_only_polls_existing_task_and_keeps_changed_source_result(images):
    await prepare_board(images)
    p, pid, card, _, calls, control = images
    control['poll_error'] = True
    job = await queue(images)
    assert (await p.run_image_job(job['id']))['status'] == 'recoverable'
    current = await p._character_repository.get(card['id'])
    current['referenceImageVersion'] = 'replaced'
    await p._character_repository.save(current)
    control['poll_error'] = False
    await p.recover_image_job(pid, job['id'])
    done = await p.run_image_job(job['id'])
    assert done['status'] == 'succeeded' and done['applied'] is False
    assert not (await p._character_repository.get(card['id'])).get('referenceBoardCandidate')
    assert (await p._image_job_store.get(job['id']))['results']['board-candidate']['objectKey']
    assert calls.count('submit') == 2


@pytest.mark.parametrize('change', ['source', 'appearance', 'style'])
async def test_stale_board_cannot_be_approved(images, change):
    await prepare_board(images)
    p, pid, card, *_ = images
    job = await queue(images)
    await p.run_image_job(job['id'])
    current = await p._character_repository.get(card['id'])
    candidate = current['referenceBoardCandidate']
    if change == 'style':
        record = await p._repository.get(pid)
        record.project['visualStyleProfile'] = resolve_style('ink-animation')
        await p._repository.save(record)
    else:
        current['referenceImageObjectKey' if change == 'source' else 'appearance'] = 'changed'
        await p._character_repository.save(current)
    with pytest.raises(DomainError, match='REFERENCE_BOARD_STALE'):
        await adopt(images, candidate)


async def test_prompt_only_edit_preserves_board_candidate_and_legacy_main_supported(images):
    await prepare_board(images)
    p, _, card, *_ = images
    current = await p._character_repository.get(card['id'])
    current.pop('referenceImageVersion')
    current['referenceImageStatus'] = 'candidate'  # another main candidate doesn't unapprove main
    await p._character_repository.save(current)
    job = await queue(images)
    assert (await p.run_image_job(job['id']))['status'] == 'succeeded'
    current = await p._character_repository.get(card['id'])
    candidate = current['referenceBoardCandidate']
    current.update(referenceImagePrompt='新润色文字', revision=10)
    await p._character_repository.save(current)
    assert (await adopt(images, candidate))['character']['referenceBoard']['status'] == 'approved'


@pytest.mark.parametrize('size', ['720*1280', '9999*9999', 'bad'])
async def test_board_invalid_config_size_rejected_before_submission(images, size):
    await prepare_board(images)
    images[0]._reference_image_provider._size = size
    with pytest.raises(DomainError, match='REFERENCE_BOARD_SIZE_INVALID'):
        await queue(images)
    assert images[4].count('submit') == 1


async def test_board_invalid_actual_dimensions_do_not_install_or_resubmit(images):
    await prepare_board(images)
    output = io.BytesIO()
    Image.new('RGB', (256, 768), 'red').save(output, 'PNG')
    images[5]['board_bytes'] = output.getvalue()
    p, _, card, *_ = images
    job = await queue(images)
    result = await p.run_image_job(job['id'])
    assert result['status'] == 'failed' and result['error'] == 'REFERENCE_IMAGE_INVALID'
    assert not (await p._character_repository.get(card['id'])).get('referenceBoardCandidate')
    await p.run_image_job(job['id'])
    assert images[4].count('submit') == 2


async def test_video_uses_only_approved_board_and_keeps_one_reference_per_character(images):
    from comicflow.providers.h3_skill import reference_plan

    await prepare_board(images)
    p, pid, card, *_ = images
    record = await p._repository.get(pid)
    record.project['script'] = {'shots': [{'id': 's1', 'characterIds': [card['id']]}]}
    await p._repository.save(record)
    job = await queue(images)
    await p.run_image_job(job['id'])
    saved = await p._character_repository.get(card['id'])
    candidate = saved['referenceBoardCandidate']
    shot = {'durationSec': 5}
    before = await p._video_preparation().character_inputs(pid, 's1')
    assert not before[0].get('referenceBoardUrl')
    assert reference_plan(shot, before)['images'][0]['view'] == 'main'
    await adopt(images, candidate)
    after = await p._video_preparation().character_inputs(pid, 's1')
    plan = reference_plan(shot, after)
    assert plan['mode'] == 'ref2va' and len(plan['images']) == 1
    assert plan['images'][0]['url'].endswith(candidate['objectKey'])
    assert plan['images'][0]['id'] == card['id']
    saved = await p._character_repository.get(card['id'])
    saved['referenceImageVersion'] = 'new-main'
    await p._character_repository.save(saved)
    inputs = await p._video_preparation().character_inputs(pid, 's1')
    assert not inputs[0].get('referenceBoardUrl')


async def test_style_compiler_does_not_inherit_single_front_portrait_instruction(images):
    await prepare_board(images)
    p, pid, *_ = images
    record = await p._repository.get(pid)
    record.project['visualStyleProfile'] = resolve_style('ink-animation')
    await p._repository.save(record)
    job = await queue(images)
    saved = await p._image_job_store.get(job['id'])
    request = saved['requests']['board-candidate']
    prompt = request['visualDescription']
    assert '水墨动画' in prompt and '三列等宽' in prompt
    assert '9:16' not in prompt and '单一人物、全身清晰' not in prompt


async def test_board_http_approval_survives_broken_model_binding(images, monkeypatch):
    from dataclasses import replace

    from comicflow.api.app import create_app
    from comicflow.infrastructure.memory import create_memory_runtime

    await prepare_board(images)
    p, pid, card, *_ = images
    job = await queue(images)
    await p.run_image_job(job['id'])
    saved = await p._character_repository.get(card['id'])
    version = (await p.get_snapshot(pid))['project']['version']

    async def broken(*args):
        raise DomainError('PROVIDER_NOT_CONFIGURED')

    monkeypatch.setattr('comicflow.api.app.selected_runtime', broken)
    app = create_app(replace(create_memory_runtime(), pipeline=p))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url='http://test') as client:
        response = await client.post(
            f'/api/projects/{pid}/characters/{card["id"]}/reference-board/approve',
            json={'candidateId': saved['referenceBoardCandidate']['id'],
                  'expectedVersion': version})
    assert response.status_code == 200, response.text
    assert images[4].count('submit') == 2
