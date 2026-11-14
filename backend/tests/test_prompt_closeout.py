"""Final prompt boundaries; synthetic inputs only, real sockets forbidden."""
import socket
from copy import deepcopy

import pytest
import pytest_asyncio
from comicflow.providers.bailian_text import _script_prompt, _story_prompt
from comicflow.providers.drama_skills import prepare_visual_asset_request
from comicflow.providers.h3_skill import H3SkillPromptWriter
from test_h3_skill_execution import valid_rewrite


@pytest_asyncio.fixture(autouse=True)
async def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Real model/network access forbidden')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)


def test_story_stage_does_not_request_shot_schema():
    prompt = _story_prompt(60)
    assert '600' in prompt and 'story_expansion' in prompt
    assert '主角目标' in prompt
    assert 'actionBefore' not in prompt and 'actionDescription' not in prompt
    assert '每个镜头只承担' not in prompt


@pytest.mark.parametrize('duration', [30, 60, 90])
def test_script_prompt_uses_target_and_separates_sound_from_spoken_text(duration):
    prompt = _script_prompt(duration, mode='import_story', task='script_split')
    assert f'所有 durationSec 之和必须等于 {duration} 秒' in prompt
    assert '画外音或环境声' not in prompt
    assert '环境声写入soundscape' in prompt
    assert '对白和旁白合计' in prompt
    assert '将相机运动、情绪氛围明确写入 `actionDescription`' not in prompt
    assert 'Wide shot, low-angle.' not in prompt


@pytest.mark.parametrize('duration,budget', [(30, 105), (60, 210), (90, 315)])
def test_script_prompt_states_speech_caps_and_short_drama_pacing(duration, budget):
    prompt = _script_prompt(duration, mode='import_story', task='script_split')
    assert f'合计尽量不超过 {budget} ' in prompt and '原对白优先保留' in prompt
    for cap in ('5秒≤16字', '8秒≤28字', '15秒≤56字'):
        assert cap in prompt
    assert '前3秒' in prompt and '相邻镜头 shotSize 不重复' in prompt
    assert '末镜留下悬念' in prompt and '只写一种运镜' in prompt
    assert '粗估' not in prompt.split('竖屏短剧节奏')[0].split('故事中的画面描写')[1]


def test_script_prompt_offers_optional_scene_lighting_and_weather():
    prompt = _script_prompt(30, mode='import_story', task='script_split')
    assert 'scene 可另外提供 lighting' in prompt and 'weather' in prompt
    # Optional: the scene contract still lists the same required fields.
    assert 'id、title、time、location、narrativeGoal、conflict、turningPoint、shotIds' in prompt


def test_story_prompt_asks_for_short_drama_hook_without_lowering_length():
    prompt = _story_prompt(30)
    assert '300' in prompt and '开头直接进入异常或冲突' in prompt
    assert '不会整段作为旁白朗读' in prompt


@pytest.mark.parametrize('purpose', ['character-reference', 'scene-background'])
def test_unstyled_requests_preserve_explicit_medium_without_invented_weather(purpose):
    source = {'imagePurpose': purpose, 'visualDescription': '三维动画，明亮干燥的室内，哑光材质'}
    before = deepcopy(source)
    prompt = prepare_visual_asset_request(source)['visualDescription']
    assert prompt.startswith(source['visualDescription']) and source == before
    assert '自然肤质和真实织物纤维清晰可见' not in prompt
    assert '背景自然虚化' not in prompt
    assert '雨水在物体表面' not in prompt and '雾气、烟尘、水气增加' not in prompt


def test_image_edit_board_has_one_four_region_layout_and_source_identity():
    prompt = prepare_visual_asset_request({
        'imagePurpose': 'character-reference-board', 'visualDescription': '沿用已确认主图身份',
    })['visualDescription']
    assert '已确认主图' in prompt and '脸部特写' in prompt
    assert '右侧' in prompt and '三列等宽' in prompt
    assert '正方形或横版画布' not in prompt


@pytest.mark.parametrize('mode', ['t2va', 'ref2va'])
async def test_multi_speaker_local_skill_never_assigns_every_line_to_subject_one(mode):
    characters = [{'id': 'a', 'name': '小林'}, {'id': 'b', 'name': '店员'}]
    if mode == 'ref2va':
        for i, card in enumerate(characters):
            card['referenceImageUrl'] = f'https://assets.test/{i}.png'
    dialogue = '小林：还有饭吗？\n店员：有。'
    prompt = (await H3SkillPromptWriter(valid_rewrite).write({
        'durationSec': 5, 'dialogue': dialogue, 'narration': '夜深了。',
    }, characters))['prompt']
    assert '<Subject 1> (S1) speaks' not in prompt and 'S1 says:' not in prompt
    assert 'S1 says in an off-screen' not in prompt
    for line in dialogue.splitlines() + ['夜深了。']:
        assert prompt.count(f'<d>[Chinese] {line}</d>') == 1


async def test_local_skill_respects_authored_timing_and_stillness():
    prompt = (await H3SkillPromptWriter(valid_rewrite).write({
        'durationSec': 10, 'visualDescription': '0–8秒保持静止，8–10秒抬眼。',
    }, []))['prompt']
    assert 'opening 20%, action 60%, stable handoff 20%' not in prompt
    assert 'authored timing' in prompt and 'stillness' in prompt


async def test_explicit_off_screen_speaker_is_not_reassigned_to_the_only_visible_character():
    prompt = (await H3SkillPromptWriter(valid_rewrite).write({
        'durationSec': 5, 'dialogue': '店员：稍等。',
    }, [{'id': 'a', 'name': '小林'}]))['prompt']
    assert 'S1 says:' not in prompt
    assert prompt.count('<d>[Chinese] 店员：稍等。</d>') == 1
