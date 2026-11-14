"""Chinese short-drama authoring rules; no model calls."""
import re

import pytest
from comicflow.providers.h3_context_ir import compile_chinese_intent


def shot(**overrides):
    return {'id': 's1', 'durationSec': 5, 'visualDescription': '小林走进便利店。',
            'actionBefore': '站在门外', 'actionMiddle': '推门并穿过门口',
            'actionAfter': '身体和双脚完全在店内', **overrides}


def test_sections_and_target_follow_actual_ratio_and_never_invent_reference_media():
    result = compile_chinese_intent(shot(aspectRatio='16:9'), [])
    prompt = result['prompt']
    assert re.findall(r'^【(.+?)】$', prompt, re.M) == [
        '参考素材', '成片目标', '镜头与动作', '台词', '场景与风格', '声音', '限制',
    ]
    assert '5秒' in prompt and '16:9' in prompt and '横屏' in prompt
    assert '未提供参考素材' in prompt
    assert not any(t in prompt for t in ('@参考', '<Audio', '<Video', '冷蓝', '胶片颗粒'))
    assert result['execution']['compilerVersion'] == 4


@pytest.mark.parametrize('duration', [4, 5, 8, 10, 15])
def test_action_timing_is_contiguous_and_covers_actual_duration(duration):
    prompt = compile_chinese_intent(shot(durationSec=duration), [])['prompt']
    spans = re.findall(r'(?m)^(\d+(?:\.\d+)?)–(\d+(?:\.\d+)?)秒：(.+)$', prompt)
    assert len(spans) == 3
    assert float(spans[0][0]) == 0 and float(spans[-1][1]) == duration
    assert all(float(a[1]) == float(b[0]) for a, b in zip(spans, spans[1:], strict=False))
    assert [p[2] for p in spans] == ['站在门外', '推门并穿过门口', '身体和双脚完全在店内']
    assert '建议节奏' in prompt and '不代表三次切镜' in prompt


def test_authored_timestamps_are_preserved_without_a_second_timeline():
    authored = '0–2秒：推开门。2–5秒：走进店内。'
    prompt = compile_chinese_intent(shot(visualDescription=authored), [])['prompt']
    assert prompt.count(authored) == 1
    assert '0–1秒' not in prompt and '1–4秒' not in prompt
    assert '沿用原稿时间安排' in prompt


def test_partial_states_do_not_invent_actions_and_nested_states_are_used():
    source = shot(actionBefore='', actionMiddle='', actionAfter='',
                  continuityPlan={'actionAfter': '已坐在窗边'})
    prompt = compile_chinese_intent(source, [])['prompt']
    assert '0–5秒' in prompt and '已坐在窗边' in prompt
    assert '推门并穿过门口' not in prompt
    source['actionAfter'] = '停在门内'
    prompt = compile_chinese_intent(source, [])['prompt']
    assert '停在门内' in prompt and '已坐在窗边' not in prompt


def test_exact_two_speaker_dialogue_and_narration_do_not_conflict_with_prohibitions():
    dialogue = '小林（低声）：“还有饭吗？”\n店员：“有，稍等。”'
    narration = '他终于找到一处亮着灯的地方。'
    prompt = compile_chinese_intent(shot(dialogue=dialogue, narration=narration,
        emotion='克制', music='无背景音乐', soundscape='门铃声和雨声'),
        [{'id': 'c1', 'name': '小林'}, {'id': 'c2', 'name': '店员'}])['prompt']
    assert prompt.count(dialogue) == 1 and prompt.count(narration) == 1
    assert '不新增旁白' not in prompt and '无对白、无旁白' not in prompt
    assert '克制' in prompt and '说完闭嘴' in prompt
    assert '无背景音乐' in prompt and '钢琴' not in prompt
    assert '不能把所有台词分配给第一个角色' in prompt


def test_material_roles_use_actual_images_and_board_is_one_character():
    prompt = compile_chinese_intent(shot(referenceImages=[
        {'url': 'https://asset.test/tail.png', 'view': 'continuity-anchor'},
        {'url': 'https://asset.test/bg.png', 'view': 'scene-anchor'},
    ]), [{'id': 'c1', 'name': '小林', 'referenceBoardUrl': 'https://asset.test/c.png'}])['prompt']
    assert '<Picture 1>' in prompt and '多个视角是同一个人' in prompt
    assert '<Picture 2>' in prompt and '连续性参考' in prompt
    assert '<Picture 3>' in prompt and '场景参考' in prompt
    assert 'https://' not in prompt and '@' not in prompt


def test_referenced_characters_get_one_cue_and_action_precedes_appearance():
    appearance = '年龄感：二十四五岁左右。脸型骨相：鹅蛋脸，下颌线条清晰' + '细节' * 200
    characters = [
        {'id': 'c1', 'name': '林夏', 'appearance': appearance,
         'clothing': '服装层级：深灰蓝色防雨连帽夹克（帽子放下），内搭白T恤',
         'referenceBoardUrl': 'https://asset.test/board.png'},
        {'id': 'c2', 'name': '司机', 'appearance': '方正面孔，下颌略宽', 'clothing': '深蓝制服'},
    ]
    prompt = compile_chinese_intent(shot(), characters)['prompt']
    assert ('林夏（外貌与服装以<Picture 1>为准），'
            '辨识点：二十四五岁左右；深灰蓝色防雨连帽夹克') in prompt
    assert '细节细节' not in prompt and '鹅蛋脸' not in prompt
    # Without a reference image the authored look is the only identity source.
    assert '外貌：方正面孔，下颌略宽' in prompt and '服装：深蓝制服' in prompt
    assert prompt.index('【镜头与动作】') < prompt.index('辨识点')


def test_final_frame_is_explicit_and_forbids_returning_to_reference_pose():
    prompt = compile_chinese_intent(shot(), [])['prompt']
    assert '末帧画面：身体和双脚完全在店内。' in prompt
    assert '不回到参考图的正面站姿' in prompt
    no_final = compile_chinese_intent(shot(actionAfter=''), [])['prompt']
    assert '末帧画面' not in no_final


def test_silent_shot_does_not_request_breath_or_extra_music():
    prompt = compile_chinese_intent(shot(soundscape='全片静音', music='无'), [])['prompt']
    assert '无对白、无旁白' in prompt and '全片静音' in prompt
    assert '呼吸' not in prompt
    assert '静音或无配乐要求优先' in prompt
