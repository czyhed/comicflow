"""Offline regression: the app, not the model, decides which Chinese survives.

The alias pass used to replace only the exact full name, so a name carrying a
Chinese possessive or a structural noun (``李俊杰的外观``) still tripped the
language gate and rejected an expansion the user had already paid for. These
tests pin the closed vocabulary that may be rewritten, and keep everything else
a hard rejection.
"""

import pytest
from comicflow.providers.h3_language import (
    contains_chinese_prose,
    normalize_character_names,
)

ALIASES = {'李俊杰': 'Character 1'}
FULL_NAME = '李俊杰'


@pytest.mark.parametrize('text,expected', [
    # The exact name is already handled; these are the shapes that leaked.
    ('<Subject 1> is 李俊杰.', '<Subject 1> is Character 1.'),
    ('<Subject 1> (李俊杰) ([Shot 1]): fully_preserved.',
     '<Subject 1> (Character 1) ([Shot 1]): fully_preserved.'),
    ('<Subject 1> (李俊杰的外观): fully_preserved.',
     "<Subject 1> (Character 1's appearance): fully_preserved."),
    ('<Subject 1> keeps 李俊杰的外观: fully_preserved.',
     "<Subject 1> keeps Character 1's appearance: fully_preserved."),
    ('<Subject 1> keeps 李俊杰的服装 and 李俊杰的发型.',
     "<Subject 1> keeps Character 1's clothing and Character 1's hairstyle."),
    ('<Subject 1> is 李俊杰之形象.', "<Subject 1> is Character 1's image."),
    ('<Subject 1> keeps 俊杰的外观.', "<Subject 1> keeps Character 1's appearance."),
    ('<Subject 1> (李俊杰，[Shot 1]): fully_preserved.',
     '<Subject 1> (Character 1,[Shot 1]): fully_preserved.'),
])
def test_known_name_forms_become_the_english_alias(text, expected):
    assert normalize_character_names(text, ALIASES) == expected


@pytest.mark.parametrize('text', [
    '<Subject 1> keeps 格子衬衫和微卷碎发: fully_preserved.',
    '<Subject 1> ([Shot 1]): 完全保留.',
    '<Subject 1> is 俊杰明 from <Picture 1>.',
    '<Subject 1> keeps his look: fully_preserved 完全保留.',
    '<Subject 1> 光着脚.',
])
def test_any_other_chinese_is_still_rejected(text):
    assert contains_chinese_prose(normalize_character_names(text, ALIASES))


def test_ambiguous_given_names_are_not_reassigned():
    """Two characters sharing a given name must never be collapsed into one."""
    aliases = {'李俊杰': 'Character 1', '王俊杰': 'Character 2'}
    text = '<Subject 1> keeps 俊杰的外观.'
    assert normalize_character_names(text, aliases) == text


def test_structural_vocabulary_is_closed():
    """Only the listed nouns are translated; the rest stays Chinese on purpose."""
    text = '<Subject 1> keeps 李俊杰的宠物.'
    assert '宠物' in normalize_character_names(text, ALIASES)


async def test_a_name_with_a_chinese_noun_inside_retention_analysis_no_longer_blocks():
    """The reported 502: `reason=language` from `retention_analysis`."""
    from comicflow.providers.h3_skill import H3SkillPromptWriter

    sections = {
        'subject_definitions': '<Subject 1> is 李俊杰 from <Picture 1>.',
        'summary': '[reference generation] 李俊杰 walks to the machine.',
        'retention_analysis': '<Subject 1> (李俊杰的外观, [Shot 1]): fully_preserved.',
        'detailed_description': '[Shot 1] 李俊杰 stops beside <Picture 1>.',
        'overall_soundscape': 'Corridor ambience.',
        'non_diegetic_music': 'N/A',
    }
    characters = [{
        'id': 'c1', 'name': '李俊杰', 'referenceImageUrl': 'https://assets.test/c1.png',
    }]

    async def complete(system, user):
        assert 'no Chinese characters at all' in system
        return {'durationSec': 5, 'sections': dict(sections)}

    result = await H3SkillPromptWriter(complete).write({
        'id': 'shot_1', 'durationSec': 5, 'generationMode': 'ref2va',
    }, characters)
    prompt = result['prompt']
    assert '李俊杰' not in prompt
    assert "Character 1's appearance" in prompt


async def test_chinese_the_alias_pass_cannot_resolve_still_rejects_safely(caplog):
    from comicflow.providers.h3_skill import (
        H3PromptValidationError,
        H3SkillPromptWriter,
    )

    sections = {
        'subject_definitions': '<Subject 1> is Character 1 from <Picture 1>.',
        'summary': '[reference generation] <Subject 1> waits.',
        'retention_analysis': '<Subject 1> ([Shot 1]): 完全保留.',
        'detailed_description': '[Shot 1] Character 1 waits beside <Picture 1>.',
        'overall_soundscape': 'Corridor ambience.',
        'non_diegetic_music': 'N/A',
    }

    async def complete(system, user):
        return {'durationSec': 5, 'sections': dict(sections)}

    with pytest.raises(H3PromptValidationError) as error:
        await H3SkillPromptWriter(complete).write({
            'id': 'shot_1', 'durationSec': 5, 'generationMode': 'ref2va',
        }, [{'id': 'c1', 'name': '李俊杰',
             'referenceImageUrl': 'https://assets.test/c1.png'}])
    assert error.value.reason == 'language'
    assert error.value.section == 'retention_analysis'
    assert '完全保留' not in caplog.text
