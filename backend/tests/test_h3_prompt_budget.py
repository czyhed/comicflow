"""Offline final-prompt budgeting, including app-owned speech and frame prefixes."""

import json
import socket

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from test_h3_skill_execution import valid_rewrite


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('Prompt budget tests must not use real sockets')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)


@pytest.mark.parametrize('mode', ['t2va', 'i2va', 'fl2va', 'l2va', 'ref2va'])
async def test_skill_budget_reserves_app_text_and_preserves_all_references(mode):
    calls = []
    shot = {
        'id': 's2', 'durationSec': 5, 'generationMode': mode,
        'dialogue': '（轻声）你也听见了吗？', 'narration': '他望向柜台，脚步停住。',
    }
    characters = []
    if mode in {'i2va', 'fl2va'}:
        shot['firstFrameUrl'] = 'https://assets.test/first.png'
    if mode in {'l2va', 'fl2va'}:
        shot['lastFrameUrl'] = 'https://assets.test/last.png'
    if mode == 'ref2va':
        characters = [{'id': f'c{i}', 'referenceImageUrl': f'https://assets.test/c{i}.png'}
                      for i in range(1, 3)]
        shot['referenceImages'] = [
            {'url': f'https://assets.test/ref{i}.png', 'view': 'continuity-anchor'}
            for i in range(3, 10)
        ]

    async def complete(system, user):
        data = json.loads(user)
        budget = data['promptBudget']
        calls.append(budget)
        assert 'promptBudget' in system and 'characters, not tokens' in system
        assert budget['maxPromptCharacters'] == 7000
        assert sum(budget['sectionTargets'].values()) == budget['maxSectionTextCharacters']
        assert budget['maxSectionTextCharacters'] + budget['reservedCharacters'] <= 7000
        result = await valid_rewrite(system, user)
        description = ('detailed_description' if mode == 'ref2va'
                       else 'integrated_multimodal_description')
        used = sum(len(s) for s in result['sections'].values())
        padding = budget['maxSectionTextCharacters'] - used
        result['sections'][description] += (' Soft light.' * (padding // 12 + 1))[:padding]
        return result

    compiled = await H3SkillPromptWriter(complete).write(shot, characters)
    assert len(calls) == 1
    assert len(compiled['prompt']) <= 7000
    for line in [shot['dialogue'], shot['narration']]:
        assert f'<d>[Chinese] {line}</d>' in compiled['prompt']
    if mode == 'ref2va':
        for i in range(1, 10):
            assert f'<Picture {i}>' in compiled['prompt']
    elif mode in {'i2va', 'fl2va'}:
        assert '0.00' in compiled['prompt']


async def test_reference_expansion_no_longer_overflows_due_to_generic_app_appendix():
    async def complete(system, user):
        result = await valid_rewrite(system, user)
        result['sections']['subject_definitions'] += ' <Subject 2> is the cashier.'
        result['sections']['detailed_description'] += (
            ' <Subject 2> keeps both feet behind the counter, facing <Subject 1>.'
        )
        used = sum(len(s) for s in result['sections'].values())
        result['sections']['detailed_description'] += 'x' * (5200 - used)
        return result

    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            prompt = json.loads(request.content)['content'][0]['text']
            assert len(prompt) <= 7000
            assert 'both feet behind the counter' in prompt
            assert '<Picture 1>' in prompt and '<Picture 2>' in prompt
            assert '<d>[Chinese] 有人吗？</d>' in prompt
            return httpx.Response(200, json={'task_id': 'offline'})
        if '/query/' in request.url.path:
            return httpx.Response(200, json={'task': {
                'status': 'succeeded', 'content': {'url': 'https://assets.test/video.mp4'},
            }})
        return httpx.Response(200, content=b'offline')

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(complete), poll_interval_seconds=0,
    )
    await provider.generate({'id': 's2', 'durationSec': 5, 'dialogue': '有人吗？'}, [
        {'id': 'c1', 'referenceImageUrl': 'https://assets.test/c1.png'},
        {'id': 'c2', 'referenceImageUrl': 'https://assets.test/c2.png'},
    ])
    assert calls == ['POST', 'GET', 'GET']


async def test_oversized_source_speech_stops_before_paid_text_call():
    calls = []

    async def complete(system, user):
        calls.append(user)
        return await valid_rewrite(system, user)

    with pytest.raises(RuntimeError, match='^VIDEO_PROMPT_TOO_LONG$') as caught:
        await H3SkillPromptWriter(complete).write({
            'id': 's2', 'durationSec': 5, 'dialogue': '原始台词' * 1800,
        }, [])
    assert not calls
    assert caught.value.detail['textExpansionAttempted'] is False


async def test_noncompliant_model_is_not_truncated_or_retried(caplog):
    text_calls, video_calls = [], []

    async def complete(system, user):
        text_calls.append(user)
        result = await valid_rewrite(system, user)
        result['sections']['integrated_multimodal_description'] += ' private-text' * 700
        return result

    def handler(request):
        video_calls.append(request)
        pytest.fail('Oversized prompt must never reach H3')

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(complete),
    )
    with pytest.raises(RuntimeError, match='^VIDEO_PROMPT_TOO_LONG$') as caught:
        await provider.generate({'id': 's2', 'durationSec': 5}, [])
    assert len(text_calls) == 1 and not video_calls
    assert caught.value.detail['promptCharacters'] > 7000
    assert caught.value.detail['maxCharacters'] == 7000
    assert caught.value.detail['textExpansionAttempted'] is True
    assert 'private-text' not in caplog.text


@pytest.mark.parametrize('oversized_source', [False, True])
async def test_length_failure_reaches_api_without_video_or_saved_asset(oversized_source):
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，两个人在便利店内轻声交谈。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{
        'id': 's2', 'durationSec': 5,
        'dialogue': '原始台词' * 1800 if oversized_source else '有人吗？',
    }]}
    await runtime.pipeline._repository.save(record)
    text_calls = []

    async def complete(system, user):
        text_calls.append(user)
        result = await valid_rewrite(system, user)
        result['sections']['integrated_multimodal_description'] += ' private-text' * 700
        return result

    def handler(request):
        pytest.fail('Length failure must not submit a video')

    provider = MinimaxH3Provider(api_key='offline', transport=httpx.MockTransport(handler))
    runtime.pipeline.set_video_provider(provider)
    provider.set_prompt_writer(H3SkillPromptWriter(complete))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s2/visual', json={
            'expectedVersion': record.project['version'],
        })
    assert response.status_code == 400
    detail = response.json()
    assert detail['error'] == 'VIDEO_PROMPT_TOO_LONG'
    assert detail['stage'] == 'h3_prompt'
    assert detail['maxCharacters'] == 7000 and detail['promptCharacters'] > 7000
    assert detail['textExpansionAttempted'] is not oversized_source
    assert len(text_calls) == (0 if oversized_source else 1)
    assert not (await runtime.pipeline._repository.get(pid)).project.get('visualAssets')
    assert 'private-text' not in response.text
