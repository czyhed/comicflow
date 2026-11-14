"""The application owns the spoken text: models only write English descriptions.

The H3 Skill previously required the text model to reproduce every dialogue and
narration line byte-for-byte inside `<d>[Chinese] ...</d>`. Models routinely
reformat an inner-monologue line, translate its parenthetical, or normalize
punctuation, and each such rewrite rejected an already-paid expansion with
`reason=dialogue`. These tests pin the replacement contract: the application
strips whatever the model produced and injects the project's own lines verbatim.
"""

import json

import pytest
from comicflow.providers.h3_skill import (
    H3PromptValidationError,
    H3SkillPromptWriter,
    speech_lines,
)

REFERENCE_IMAGES = [
    {'id': 'c1', 'name': '李俊杰', 'objectKey': 'characters/c1.png',
     'url': 'https://assets.test/c1.png'},
    {'id': 'c2', 'name': '王小红', 'objectKey': 'characters/c2.png',
     'url': 'https://assets.test/c2.png'},
]
REFERENCE_CHARACTERS = [
    {'id': 'c1', 'name': '李俊杰', 'referenceImageUrl': 'https://assets.test/c1.png'},
    {'id': 'c2', 'name': '王小红', 'referenceImageUrl': 'https://assets.test/c2.png'},
]


def sections(description):
    return {'durationSec': 5, 'sections': {
        'integrated_multimodal_description': description,
        'overall_soundscape': 'Coins clink; a soft beep.',
        'non_diegetic_music': 'N/A',
    }}


async def test_model_that_never_writes_dialogue_still_yields_verbatim_speech():
    async def complete(system, user):
        # No <d> block at all: the model only describes the visuals.
        return sections('[Shot 1] A student feeds coins into a vending machine.')

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_2', 'durationSec': 5,
        'dialogue': '（内心OS）兄弟，这次别掉链子……\n等一下！',
    }, [])
    prompt = result['prompt']
    assert '<d>[Chinese] （内心OS）兄弟，这次别掉链子……</d>' in prompt
    assert '<d>[Chinese] 等一下！</d>' in prompt
    assert prompt.count('<d>') == 2


async def test_narration_is_injected_as_an_off_screen_voiceover():
    async def complete(system, user):
        return sections('[Shot 1] A student runs down the corridor.')

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_1', 'durationSec': 5, 'narration': '李俊杰饿得前胸贴后背',
    }, [])
    prompt = result['prompt']
    assert 'says in an off-screen voiceover' in prompt
    assert '<d>[Chinese] 李俊杰饿得前胸贴后背</d>' in prompt


async def test_narration_over_an_on_screen_character_keeps_the_lips_closed_rule():
    async def complete(system, user):
        return sections('[Shot 1] Character 1 runs down the corridor.')

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_1', 'durationSec': 5, 'narration': '他饿得前胸贴后背',
    }, [{'id': 'c1', 'name': '李俊杰', 'appearance': '短发'}])
    prompt = result['prompt']
    assert 'says in an off-screen voiceover' in prompt
    assert 'lips remain completely closed' in prompt
    assert '<d>[Chinese] 他饿得前胸贴后背</d>' in prompt


async def test_injected_dialogue_keeps_source_order_and_follows_its_shot():
    async def complete(system, user):
        return sections(
            '[Shot 1] A student shakes the machine. '
            '[Shot 2] At 00:03.000, the camera cuts to his face.'
        )

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_1', 'durationSec': 5,
        'dialogue': '第一句\n第二句', 'narration': '旁白一句',
    }, [])
    prompt = result['prompt']
    description = prompt.split('overall_soundscape:')[0]
    assert description.index('<d>[Chinese] 第一句</d>') > description.index('[Shot 1]')
    assert description.index(
        '<d>[Chinese] 第二句</d>'
    ) > description.index('<d>[Chinese] 第一句</d>')
    assert description.index(
        '<d>[Chinese] 旁白一句</d>'
    ) > description.index('<d>[Chinese] 第二句</d>')


def test_speech_lines_are_trimmed_but_never_rewritten():
    shot = {'dialogue': '  第一句  \n\n 第二句\n', 'narration': '旁白'}
    assert speech_lines(shot) == [
        ('dialogue', '第一句'), ('dialogue', '第二句'), ('narration', '旁白'),
    ]
    assert speech_lines({'dialogue': '', 'narration': None}) == []


async def test_dialogue_from_the_model_is_replaced_not_duplicated():
    async def complete(system, user):
        return sections(
            '[Shot 1] A student feeds coins into a vending machine. '
            'He mutters <d>[Chinese] 兄弟，这次别掉链子</d>'
        )

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_2', 'durationSec': 5, 'dialogue': '（内心OS）兄弟，这次别掉链子……',
    }, [])
    prompt = result['prompt']
    assert prompt.count('<d>') == 1
    assert '<d>[Chinese] （内心OS）兄弟，这次别掉链子……</d>' in prompt


async def test_a_section_without_a_shot_marker_is_still_rejected():
    async def complete(system, user):
        return sections('A student runs through a hallway.')

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({
            'durationSec': 5, 'dialogue': '你好',
        }, [])
    assert error.value.reason == 'shots'


@pytest.mark.parametrize('echo', [
    '{line}',
    'He mutates {line}',
    '{line} and then he laughs',
])
async def test_chinese_the_model_writes_into_the_description_is_still_rejected(echo):
    """The known residual: a model that ignores the contract fails loudly.

    The application cannot tell an echo of a spoken line from any other Chinese
    prose, and silently deleting half of a sentence would be worse than refusing
    the request, so this stays a visible, diagnosable rejection.
    """
    line = '（内心OS）兄弟，这次别掉链子……'

    async def complete(system, user):
        return sections(f'[Shot 1] He thinks {echo.format(line=line)}')

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({
            'id': 'shot_2', 'durationSec': 5, 'dialogue': line,
        }, [])
    assert error.value.reason == 'language'
    assert error.value.section == 'integrated_multimodal_description'


async def test_chinese_that_is_not_a_project_line_still_fails_the_language_gate():
    async def complete(system, user):
        return sections('[Shot 1] He thinks 这次一定行……')

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({
            'id': 'shot_2', 'durationSec': 5, 'dialogue': '你好',
        }, [])
    assert error.value.reason == 'language'


async def test_fully_referenced_shots_inject_speech_into_detailed_description():
    async def complete(system, user):
        return {'durationSec': 5, 'sections': {
            'subject_definitions': (
                '<Subject 1> is Character 1 from <Picture 1>. '
                '<Subject 2> is Character 2 from <Picture 2>.'
            ),
            'summary': '[reference generation] <Subject 1> and <Subject 2> wait.',
            'retention_analysis': (
                '<Subject 1> (appears in [Shot 1]): fully_preserved - appearance. '
                '<Subject 2> (appears in [Shot 1]): fully_preserved - appearance.'
            ),
            'detailed_description': (
                '[Shot 1] Character 1 waits beside Character 2 from <Picture 1> '
                'and <Picture 2>.'
            ),
            'overall_soundscape': 'Corridor ambience.',
            'non_diegetic_music': 'N/A',
        }}

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_1', 'durationSec': 5, 'generationMode': 'ref2va',
        'dialogue': '李俊杰，等一下！', 'referenceImages': REFERENCE_IMAGES,
    }, [])
    prompt = result['prompt']
    detailed = prompt.split('detailed_description:')[1].split('overall_soundscape:')[0]
    assert '<d>[Chinese] 李俊杰，等一下！</d>' in detailed
    assert '<d>' not in prompt.split('detailed_description:')[0]


async def test_prompt_contract_asks_the_model_to_leave_spoken_text_to_the_application():
    seen = {}

    async def complete(system, user):
        seen['system'] = system
        return sections('[Shot 1] A student runs.')

    await H3SkillPromptWriter(complete).write({
        'id': 'shot_1', 'durationSec': 5, 'dialogue': '你好',
    }, [])
    contract = seen['system'].split('Execution contract:')[1]
    assert 'Never write a <d> block' in contract
    assert 'verbatim' in contract  # the application appends the lines itself


async def test_speech_survives_the_json_round_trip_into_the_provider_payload():
    """The lines reach the vendor call exactly as the project stored them."""
    import httpx
    from comicflow.providers.minimax_h3 import MinimaxH3Provider

    line = '（内心OS）兄弟，这次别掉链子……'
    submitted = {}

    async def complete(system, user):
        return sections('[Shot 1] A student feeds coins into a vending machine.')

    def handler(request):
        if request.method == 'POST':
            submitted['text'] = json.loads(request.content)['content'][0]['text']
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
    await provider.generate({'id': 'shot_2', 'durationSec': 5, 'dialogue': line}, [])
    assert f'<d>[Chinese] {line}</d>' in submitted['text']
