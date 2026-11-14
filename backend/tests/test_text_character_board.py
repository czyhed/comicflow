"""Text board contract through the actual chat-image adapter, entirely offline."""
import base64
import io
import json

import httpx
import pytest
import test_durable_image_jobs as fixtures
from comicflow.domain.errors import DomainError
from comicflow.production.reference_images import reference_asset_is_current
from comicflow.production.visual_styles import resolve_style
from comicflow.providers.h3_skill import reference_plan
from comicflow.providers.openai_image import OpenAIImageProvider
from PIL import Image

images = fixtures.images
sql_images = fixtures.sql_images


def chat_provider(data, size=(1536, 1024)):
    p = data[0]
    output = io.BytesIO()
    Image.new('RGB', size, 'navy').save(output, 'PNG')
    encoded = base64.b64encode(output.getvalue()).decode()
    bodies = []

    def handler(request):
        assert request.method == 'POST' and request.url.path == '/v1/chat/completions'
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {
            'content': f'![board](data:image/png;base64,{encoded})'}}]})

    provider = OpenAIImageProvider(api_key='offline-only', base_url='https://offline.invalid',
        model='gpt-image-2.5', asset_store=p._asset_store, transport=httpx.MockTransport(handler))

    class Selection:
        def provider(self, purpose, fallback):
            assert purpose == 'image', 'Text boards must not select image-edit'
            return provider

    class Bound:
        selection = Selection()
        fallback = None

    p.set_reference_image_provider(Bound())
    return bodies


async def queue(data, operation='text-board'):
    p, pid, card, *_ = data
    return await p.request_image_job(pid, card['id'],
        expected_version=(await p.get_snapshot(pid))['project']['version'],
        operation_id=operation, purpose='text-board')


async def test_text_board_without_main_single_call_atomic_approval_and_h3(sql_images):
    data, _ = sql_images
    p, pid, card, *_ = data
    bodies = chat_provider(data)
    current = await p._character_repository.get(card['id'])
    current['referenceImagePrompt'] = 'OLD FRONT ONLY 9:16'
    await p._character_repository.save(current)
    record = await p._repository.get(pid)
    record.project['visualStyleProfile'] = resolve_style('ink-animation')
    record.project['script'] = {'shots': [{'id': 's1', 'characterIds': [card['id']]}]}
    await p._repository.save(record)
    job = await queue(data)
    assert (await queue(data))['id'] == job['id']
    done = await p.run_image_job(job['id'])
    assert done['status'] == 'succeeded', done
    await p.run_image_job(job['id'])
    assert len(bodies) == 1 and done['callsStarted'] == 1
    prompt = bodies[0]['messages'][0]['content']
    assert isinstance(prompt, str)
    for text in ('黑色短发', '蓝色外套', '脸部特写', '正面', '90°', '背面', '水墨动画'):
        assert text in prompt
    for text in ('OLD FRONT ONLY', '9:16', '保持主图', '8K'):
        assert text not in prompt
    assert bodies[0]['model'] == 'gpt-image-2.5'
    assert 'quality' not in bodies[0] and 'size' not in bodies[0]
    saved = await p._character_repository.get(card['id'])
    candidate = saved['referenceBoardCandidate']
    assert candidate['generationMode'] == 'single-text-board'
    assert candidate['layout'] == ['face', 'front', 'profile', 'back']
    assert candidate['skillExecution']['task'] == 'character-text-board'
    assert 'sourceImageVersion' not in candidate and 'sourceReferenceId' not in candidate
    assert not saved.get('referenceImageUrl')
    assert not reference_asset_is_current(saved, candidate)
    before = await p._video_preparation().character_inputs(pid, 's1')
    assert not before[0].get('referenceBoardUrl')
    version = (await p.get_snapshot(pid))['project']['version']
    approved = await p.approve_character_reference_board(pid, card['id'], candidate['id'],
        expected_version=version)
    adopted = approved['character']
    assert reference_asset_is_current(adopted, adopted['referenceBoard'])
    again = await p.approve_character_reference_board(pid, card['id'], candidate['id'],
        expected_version=version)
    assert again['projectVersion'] == version + 1
    plan = reference_plan({'durationSec': 5},
        await p._video_preparation().character_inputs(pid, 's1'))
    assert len(plan['images']) == 1 and plan['mode'] == 'ref2va'
    assert plan['images'][0]['url'].endswith(candidate['objectKey'])
    assert len(bodies) == 1


@pytest.mark.parametrize('field', ['appearance', 'clothing', 'style'])
async def test_text_board_changed_source_rejects_approval(images, field):
    p, pid, card, *_ = images
    chat_provider(images)
    await p.run_image_job((await queue(images))['id'])
    current = await p._character_repository.get(card['id'])
    candidate = current['referenceBoardCandidate']
    if field == 'style':
        record = await p._repository.get(pid)
        record.project['visualStyleProfile'] = resolve_style('ink-animation')
        await p._repository.save(record)
    else:
        current[field] = 'changed'
        await p._character_repository.save(current)
    with pytest.raises(DomainError, match='REFERENCE_BOARD_STALE'):
        await p.approve_character_reference_board(pid, card['id'], candidate['id'],
            expected_version=(await p.get_snapshot(pid))['project']['version'])


async def test_text_board_does_not_bypass_unknown_character_slot(images):
    p, pid, card, version, calls, control = images
    control['submit_error'] = True
    old = await p.request_image_job(pid, card['id'], expected_version=version,
        operation_id='old', purpose='candidate')
    assert (await p.run_image_job(old['id']))['status'] == 'unknown'
    bodies = chat_provider(images)
    with pytest.raises(DomainError, match='IMAGE_JOB_ACTIVE'):
        await queue(images)
    assert not bodies and calls.count('submit') == 1


async def test_text_board_portrait_result_not_installed_or_retried(images):
    p, _, card, *_ = images
    bodies = chat_provider(images, (512, 768))
    job = await queue(images)
    done = await p.run_image_job(job['id'])
    assert done['status'] == 'failed' and done['error'] == 'REFERENCE_IMAGE_INVALID'
    assert not (await p._character_repository.get(card['id'])).get('referenceBoardCandidate')
    await p.run_image_job(job['id'])
    assert len(bodies) == 1


async def test_text_board_http_queue_returns_job_without_inline_generation(images, monkeypatch):
    from dataclasses import replace

    from comicflow.api.app import create_app
    from comicflow.infrastructure.memory import create_memory_runtime

    p, pid, card, version, *_ = images
    bodies = chat_provider(images)
    runtime = replace(create_memory_runtime(), pipeline=p)

    async def selected(*args):
        return runtime

    monkeypatch.setattr('comicflow.api.app.selected_image_runtime', selected)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        response = await client.post(f'/api/projects/{pid}/characters/{card["id"]}/image-jobs',
            json={'purpose': 'text-board', 'expectedVersion': version, 'operationId': 'http'})
        assert response.status_code == 202, response.text
        assert response.json()['purpose'] == 'text-board' and not bodies
        assert (await p.run_image_job(response.json()['id']))['status'] == 'succeeded'
        assert len(bodies) == 1
