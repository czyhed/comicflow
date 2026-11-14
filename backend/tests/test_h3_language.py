"""Offline regression for the H3 language boundary; never use a real model."""

import json
import socket

import httpx
import pytest
from comicflow.providers.h3_skill import H3PromptValidationError, H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('No network is allowed in H3 language tests')

    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)


def sections(description):
    return {'durationSec': 5, 'sections': {
        'subject_definitions': '<Subject 1> is 李俊杰 from <Picture 1>.',
        'summary': '李俊杰 walks toward the vending machine.',
        'retention_analysis': '<Subject 1> keeps his uniform.',
        'detailed_description': description,
        'overall_soundscape': 'Footsteps echo in the corridor.',
        'non_diegetic_music': 'N/A',
    }}


CHARACTERS = [{'id': 'c1', 'name': '李俊杰', 'referenceImageUrl': 'https://assets.test/c.png'}]


async def test_known_name_is_normalized_but_original_speech_and_visible_text_are_unchanged():
    calls = []
    response = sections(
        '[Shot 1] 李俊杰 (S1) walks. A badge reads "李俊杰". '
        'He says <d>[Chinese] 李俊杰，等一下！</d>'
    )

    async def complete(system, user):
        calls.append((system, user))
        return response

    result = await H3SkillPromptWriter(complete).write({
        'durationSec': 5, 'dialogue': '李俊杰，等一下！',
    }, CHARACTERS)
    assert len(calls) == 1
    assert '<Subject 1> is Character 1 from <Picture 1>.' in result['prompt']
    assert '[Shot 1] Character 1 (S1) walks.' in result['prompt']
    assert 'A badge reads "李俊杰".' in result['prompt']
    assert '<d>[Chinese] 李俊杰，等一下！</d>' in result['prompt']
    assert response['sections']['summary'].startswith('李俊杰')
    assert CHARACTERS[0]['name'] == '李俊杰'


@pytest.mark.parametrize('section', ['summary', 'detailed_description', 'overall_soundscape'])
async def test_real_chinese_prose_still_fails_with_safe_section(section, caplog):
    response = sections('[Shot 1] A student walks.')
    response['sections']['subject_definitions'] = '<Subject 1> is a student from <Picture 1>.'
    response['sections']['summary'] = 'A student walks.'
    response['sections'][section] += ' 私密画面描述'

    async def complete(system, user):
        return response

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({'durationSec': 5}, CHARACTERS)
    assert error.value.reason == 'language'
    assert error.value.section == section
    assert '私密' not in caplog.text


@pytest.mark.parametrize('name', ['未知角色', '李俊杰明', '李俊杰跑向机器'])
async def test_unknown_partial_names_and_chinese_actions_are_not_silently_repaired(name):
    async def complete(system, user):
        return sections(f'[Shot 1] {name} walks.')

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({'durationSec': 5}, CHARACTERS)
    assert error.value.reason == 'language'


@pytest.mark.parametrize('names', [['小明', '小明'], ['雨']])
async def test_ambiguous_or_single_character_names_are_not_reassigned(names):
    characters = [{'id': f'c{index}', 'name': name} for index, name in enumerate(names)]

    async def complete(system, user):
        assert json.loads(user)['characterAliases'] == {}
        return {'durationSec': 5, 'sections': {
            'integrated_multimodal_description': f'[Shot 1] {names[0]} walks.',
            'overall_soundscape': 'Footsteps.', 'non_diegetic_music': 'N/A',
        }}

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({'durationSec': 5}, characters)
    assert error.value.reason == 'language'


async def test_two_characters_keep_distinct_identities_in_provider_payload():
    characters = [*CHARACTERS, {
        'id': 'c2', 'name': '王小红', 'referenceImageUrl': 'https://assets.test/c2.png',
    }]
    events = []

    async def complete(system, user):
        events.append('text')
        assert json.loads(user)['characterAliases'] == {
            '李俊杰': 'Character 1', '王小红': 'Character 2',
        }
        response = sections('[Shot 1] 李俊杰 follows 王小红. <Subject 2> waves.')
        response['sections']['subject_definitions'] += (
            ' <Subject 2> is 王小红 from <Picture 2>.'
        )
        return response

    def handler(request):
        if request.method == 'POST':
            events.append('submit')
            prompt = json.loads(request.content)['content'][0]['text']
            assert '[Shot 1] Character 1 follows Character 2.' in prompt
            assert '<Subject 2> is Character 2 from <Picture 2>.' in prompt
            return httpx.Response(200, json={'task_id': 'offline'})
        if '/query/' in request.url.path:
            return httpx.Response(200, json={
                'task': {'status': 'succeeded', 'content': {'url': 'https://assets.test/out.mp4'}},
            })
        return httpx.Response(200, content=b'offline-test-only')

    provider = MinimaxH3Provider(
        api_key='offline', prompt_writer=H3SkillPromptWriter(complete),
        transport=httpx.MockTransport(handler),
    )
    await provider.generate({'id': 'shot', 'durationSec': 5}, characters)
    assert events == ['text', 'submit']


def test_untrusted_section_never_leaks_to_diagnostics(caplog):
    error = H3PromptValidationError('language', section='private-source-text')
    assert error.section is None
    assert 'private-source-text' not in caplog.text
