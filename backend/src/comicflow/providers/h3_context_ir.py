"""Assemble authored Chinese intent for CompShare's Context-IR, without an LLM call.

This is not an execution of the bundled English H3 Skill. The gateway owns
the subsequent optimization; its final optimized text is not available here.
"""
from __future__ import annotations

import hashlib
import re

from comicflow.domain.models import JsonObject
from comicflow.providers.h3_errors import H3_MAX_PROMPT_CHARACTERS, H3PromptLengthError
from comicflow.providers.h3_skill import reference_plan

COMPILER_VERSION = 4
_TIMING = re.compile(r'\d+(?:\.\d+)?\s*(?:秒|s\b)|\d{1,2}:\d{2}', re.I)
_CLAUSE = re.compile(r'[，,。；;、\n（(]')
_FIELD_LABEL = re.compile(r'^[^：:]{1,6}[：:]')


def _text(source: JsonObject, key: str) -> str:
    value = source.get(key)
    return value.strip() if isinstance(value, str) else ''


def _brief(text: str, limit: int = 20) -> str:
    """First authored clause only; the reference image carries the full look."""
    # Authored cards often read "年龄感：二十四五岁；发型：…"; drop such field labels.
    clauses = (_FIELD_LABEL.sub('', part).strip() for part in _CLAUSE.split(text))
    return next((clause for clause in clauses if clause), '')[:limit]


def _character_lines(characters: list[JsonObject], images: list[JsonObject]) -> list[str]:
    labels: dict[object, str] = {}
    for item in images:
        if item.get('role') == 'reference_image' and item.get('id') is not None:
            labels.setdefault(item['id'], item['label'])
    lines: list[str] = []
    for index, character in enumerate(characters, 1):
        name = character.get('name') or '未命名角色'
        appearance, clothing = _text(character, 'appearance'), _text(character, 'clothing')
        label = labels.get(character.get('id'))
        if label:
            # Long appearance prose pushed the action out of focus and pulled the
            # video back to the reference pose; keep one cue and defer to the image.
            cues = '；'.join(cue for cue in (_brief(appearance), _brief(clothing)) if cue)
            lines.append(f'角色{index}：{name}（外貌与服装以{label}为准）'
                         + (f'，辨识点：{cues}' if cues else ''))
            continue
        lines.append(f'角色{index}：{name}')
        if appearance:
            lines.append(f'外貌：{appearance}')
        if clothing:
            lines.append(f'服装：{clothing}')
    return lines


def _action_states(shot: JsonObject) -> list[str]:
    continuity = shot.get('continuityPlan')
    nested = continuity if isinstance(continuity, dict) else {}
    return [_text(shot, key) or _text(nested, key)
            for key in ('actionBefore', 'actionMiddle', 'actionAfter')]


def _action_timeline(shot: JsonObject, duration: int) -> list[str]:
    states = _action_states(shot)
    authored = [_text(shot, key) for key in ('visualDescription', 'action', 'cameraMovement')]
    if any(_TIMING.search(value) for value in [*authored, *states]):
        return ['沿用原稿时间安排，不另加切镜或重复的动作时间轴。', *[
            f'{label}：{value}' for label, value in zip(
                ('动作开始状态', '动作发展', '动作完成状态'), states,
                strict=True,
            ) if value
        ]]
    if all(states):
        # A pacing suggestion, not inferred frame-accurate speech timing or three cuts.
        bounds = (0, duration * 0.2, duration * 0.8, duration)
        return [
            '以下为建议节奏，可按动作与台词自然微调，但总时长不变；'
            '三个阶段不代表三次切镜，运镜和切镜按原稿执行。',
            *[f'{bounds[i]:g}–{bounds[i + 1]:g}秒：{value}'
              for i, value in enumerate(states)],
        ]
    return [f'0–{duration}秒：按上述画面、动作和运镜连续展开，不额外添加剧情。', *[
        f'{label}：{value}' for label, value in zip(
            ('动作开始状态', '动作发展', '动作完成状态'), states,
            strict=True,
        ) if value
    ]]


def compile_chinese_intent(shot: JsonObject, characters: list[JsonObject]) -> JsonObject:
    plan = reference_plan(shot, characters)
    if not any(isinstance(shot.get(key), str) and shot[key].strip() for key in (
        'visualDescription', 'action', 'actionBefore', 'actionMiddle', 'actionAfter',
    )):
        raise RuntimeError('VIDEO_PROMPT_REQUIRED')
    parts = ['【参考素材】']

    def append_fields(source: JsonObject, fields: tuple[tuple[str, str], ...]) -> None:
        for key, label in fields:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(f'{label}：{value.strip()}')

    # Bind exactly the images that the adapter will submit, in that order.
    # No signed URLs, base64, or stale precompiled prompt enters this text.
    for item in plan['images']:
        label, role, view = item['label'], item['role'], item.get('view')
        if role == 'first_frame':
            usage = '视频首帧；从图中可见姿态、人物位置、构图和光线开始，连续发展动作。'
        elif role == 'last_frame':
            usage = '视频尾帧；动作自然发展到图中的人物位置、姿态和构图。'
        elif view == 'continuity-anchor':
            usage = ('上一镜头尾帧，参考人物站位、动作状态和光线，衔接本镜头；'
                     '这是连续性参考，不把图片中的所有人物或姿态固定不动。')
        elif view == 'scene-anchor':
            usage = '场景参考，保持建筑、门窗和主要道具的空间关系；人物身份以角色图为准。'
        elif view in {'main', 'reference-board', 'front', 'three-quarter', 'profile'}:
            usage = (
                f"角色「{item.get('name') or '未命名角色'}」参考，"
                '保持脸型、五官、肤色、年龄、发型、体型和服装一致，'
                '允许动作、机位和光照随剧情变化。'
            )
            if view == 'reference-board':
                usage += ('板中多个视角是同一个人，不生成分屏、三视图排版或重复人物；'
                          '只继承身份与服装，不继承板的摄影棚背景、正面站姿或静态构图。')
            else:
                usage += '只继承身份与服装，不继承参考图背景、正面站姿或静态构图。'
        else:
            usage = '画面参考，结合以下剧情使用，不新增图中无关人物。'
        parts.append(f'{label}：{usage}')
    if not plan['images']:
        parts.append('未提供参考素材，依据以下已保存的角色、场景和动作描述创作。')

    ratio = str(shot.get('aspectRatio') or '9:16')
    orientation = {'9:16': '竖屏', '16:9': '横屏', '1:1': '方形画幅'}.get(ratio, '')
    parts += ['【成片目标】', f"制作一段{plan['durationSec']}秒、{ratio}{orientation}短剧视频。"]
    goal = _text(shot, 'action') or _text(shot, 'title')
    parts.append(f'核心内容：{goal}' if goal else '核心内容以以下画面描述与动作过程为准。')

    # Action comes before scene/style: models weight earlier text more heavily, and
    # the 2026-09 bus-door failure had ~1000 chars of appearance ahead of the action.
    parts.append('【镜头与动作】')
    if shot.get('continuityMode') == 'previous-tail':
        parts.append('这是上一镜头的连续动作接续：从首帧的动作状态立即继续原稿动作，'
                     '保持人物行进方向和空间关系，不重演上一段、不增加开场定格。'
                     '原稿明确要求的停顿和动作终点仍保留。')
    parts.append('画面描述定义机位与空间，运镜只描述相机运动，动作三阶段描述人物路径；'
                 '沿用同一套空间方向和结束状态，不复制人物参考图的机位和站姿。')
    parts.append('原稿涉及接触或位移时，清楚呈现接触对象、移动路径和最终落点；'
                 '在原定机位与景别内保持关键动作可辨，不用遮挡、空镜或跳切替代完成过程。'
                 '未写明的动作不补造，静止或停顿按原稿保留。')
    append_fields(shot, (('visualDescription', '画面描述'), ('shotSize', '景别'),
                         ('cameraMovement', '运镜'), ('emotion', '表演情绪')))
    parts.extend(_action_timeline(shot, plan['durationSec']))
    final_state = _action_states(shot)[2]
    if final_state:
        parts.append(f'末帧画面：{final_state}。')
        parts.append('在本段时长内完成上述动作，结尾达到动作完成状态，不停在中间步骤，'
                     '也不回到参考图的正面站姿。')

    parts.append('【台词】')
    dialogue, narration = shot.get('dialogue'), shot.get('narration')
    has_dialogue = isinstance(dialogue, str) and bool(dialogue.strip())
    has_narration = isinstance(narration, str) and bool(narration.strip())
    if has_dialogue:
        parts.append('对白逐字保留，按原文的说话人分配，台词只说一次，不改写、不翻译：')
        # Do not guess that character 1 speaks every line in a multi-character scene.
        parts.append(str(dialogue))
        parts.append('原文中的角色名与括号语气是表演标注，不把这些标注读出。')
        if len(characters) > 1:
            parts.append('按原稿区分说话人与倾听者，不能把所有台词分配给第一个角色。')
        elif len(characters) == 1 and characters[0].get('name'):
            parts.append(f"未标说话人的对白由「{characters[0]['name']}」说出，原稿显式标注优先。")
        parts.append('每句台词只说一次；按原稿语气表达，句间留自然停顿。'
                     '说话时口型对应台词，说完闭嘴；其他人不跟随张嘴。')
    if has_narration:
        parts.append('以下为画外旁白，逐字保留，不让画面中人物对旁白做口型：')
        parts.append(str(narration))
    if not has_dialogue and not has_narration:
        parts.append('无对白、无旁白，不新增人声。')
    elif not has_dialogue:
        parts.append('画面中人物不说话，不新增对白。')
    elif not has_narration:
        parts.append('不新增旁白。')
    parts.append('【场景与风格】')
    parts.extend(_character_lines(characters, plan['images']))
    scene = shot.get('scene')
    if isinstance(scene, dict):
        append_fields(scene, (('title', '场景'), ('location', '地点'), ('time', '时间'),
                              ('visualDescription', '场景画面'), ('style', '场景风格'),
                              ('lighting', '光线'), ('weather', '天气')))
    append_fields(shot, (
        ('visualStyle', '视觉风格'), ('style', '画面风格'),
        ('lighting', '光线'), ('colorPalette', '色调'), ('depthOfField', '景深'),
        ('composition', '构图'),
    ))
    parts.append('光线、色调、景深和材质细节服从上述设定与参考素材，不改变已指定画风。')
    parts.append('【声音】')
    append_fields(shot, (('soundscape', '环境声'), ('soundEffects', '音效'),
                         ('music', '配乐'), ('backgroundMusic', '背景音乐')))
    parts.append('显式静音或无配乐要求优先；其余声音匹配画面动作，'
                 '有对白或旁白时保持清晰，环境声和配乐不盖住人声。')
    parts.append('【限制】')
    parts.append('保持人物身份、脸型、发型、年龄、服装和场景空间一致；'
                 '不变脸、不串脸、不无故换装，不新增剧情、台词或无关角色。')
    parts.append('不添加对白字幕、乱码、水印或额外标志；原稿要求的可见文字保持原文。'
                 '避免机械口型、手部畸形、瞬移和无动机跳切，正常切镜按原稿执行。')
    prompt = '\n'.join(parts)
    if len(prompt) > H3_MAX_PROMPT_CHARACTERS:
        raise H3PromptLengthError(len(prompt), text_expansion_attempted=False)
    return {
        'prompt': prompt,
        'plan': plan,
        'execution': {
            'mode': 'context-ir', 'inputLanguage': 'zh', 'useContextIr': True,
            'localTextCall': False, 'compilerVersion': COMPILER_VERSION,
            'inputSha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
        },
    }
