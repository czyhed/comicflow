"""Local identity normalization; never translate or discard creative prose.

The text model writes English sections, but Chinese names, a Chinese possessive
or a Chinese structural noun routinely leak into them. The application already
owns the character aliases, so it rewrites exactly those name forms into the
English alias. Any other Chinese is left untouched and rejected by the language
gate: nothing here invents a translation for prose it does not understand.
"""

from __future__ import annotations

import re
from collections import Counter

from comicflow.domain.models import JsonObject

HAN = re.compile(r'[\u3400-\u9fff]')
# Keep spoken content and visible text byte-for-byte, including original names.
PROTECTED_TEXT = re.compile(r'(<d>.*?</d>|"[^"]*")', re.S)

# A possessive/attributive particle attaches a known name to a structural noun.
PARTICLES = ('的', '之')
# Closed vocabulary: only these nouns have a fixed English equivalent. Everything
# else stays Chinese on purpose so the language gate still refuses it.
STRUCTURAL_NOUNS = {
    '外观': 'appearance',
    '外貌': 'appearance',
    '长相': 'looks',
    '服装': 'clothing',
    '衣着': 'clothing',
    '穿着': 'clothing',
    '发型': 'hairstyle',
    '头发': 'hair',
    '身份': 'identity',
    '形象': 'image',
    '特征': 'features',
    '设定': 'design',
    '声音': 'voice',
    '表情': 'expression',
    '动作': 'action',
    '性格': 'personality',
}
_FULL_WIDTH_COMMA = re.compile(r'，')


def character_aliases(characters: list[JsonObject]) -> dict[str, str]:
    names = [str(character.get('name') or '').strip() for character in characters]
    counts = Counter(names)
    return {
        name: f'Character {index}'
        for index, name in enumerate(names, 1)
        if len(name) >= 2 and HAN.search(name) and counts[name] == 1
    }


def _resolved_names(aliases: dict[str, str]) -> dict[str, str]:
    """Every name form the alias pass may rewrite, longest form first.

    A bare given name is only resolvable when exactly one alias can own it, so a
    project with two characters sharing one can never collapse them together.
    """
    resolved = dict(aliases)
    claimed: dict[str, str] = {}
    given_names: set[str] = set()
    for name in aliases:
        if len(name) < 3 or not HAN.search(name):
            continue
        given = name[1:]
        if len(given) >= 2 and HAN.search(given):
            given_names.add(given)
    for given in given_names:
        owners = {
            alias for name, alias in aliases.items() if name.endswith(given) and name != given
        }
        if len(owners) == 1:
            claimed[given] = owners.pop()
    resolved.update(claimed)
    return dict(sorted(resolved.items(), key=lambda item: len(item[0]), reverse=True))


def normalize_character_names(text: str, aliases: dict[str, str]) -> str:
    if not aliases:
        return text
    names = _resolved_names(aliases)
    pattern = re.compile(
        # Match complete names only, never part of another name or Chinese sentence.
        r'(?<![A-Za-z0-9_])(?P<name>'
        + '|'.join(map(re.escape, names))
        + r')(?![A-Za-z0-9_])'
        r'(?:(?P<particle>[的之])(?P<noun>' + '|'.join(STRUCTURAL_NOUNS) + r'))?'
        r'(?P<trailing>[的之])?'
    )

    def replace(match: re.Match[str]) -> str:
        alias = names[match.group('name')]
        noun = match.group('noun')
        if noun:
            return f"{alias}'s {STRUCTURAL_NOUNS[noun]}"
        if match.group('trailing'):
            return f"{alias}'s "
        return alias

    parts = PROTECTED_TEXT.split(text)
    swapped = ''.join(
        part if index % 2 else pattern.sub(replace, part)
        for index, part in enumerate(parts)
    )
    # Chinese punctuation is not prose; normalize it so English sentences read
    # correctly around an injected alias.
    return _FULL_WIDTH_COMMA.sub(',', swapped)


def contains_chinese_prose(text: str) -> bool:
    return HAN.search(PROTECTED_TEXT.sub('', text)) is not None
