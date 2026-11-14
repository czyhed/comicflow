"""Reference-image prompts decide the look of every later video.

The old defaults hard-coded 漫画风格 for both purposes and gave the scene prompt
no vertical instruction at all, so a project generated a 2D-anime background and
a semi-realistic character sheet to feed into one photorealistic video model.
"""

from __future__ import annotations

from comicflow.infrastructure.memory import create_memory_runtime


class RecordingImages:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, shot, characters):
        self.prompts.append(str(shot['visualDescription']))
        return {'mediaType': 'image', 'sourceUrl': 'https://assets.test/image.png'}


async def _pipeline_with_images() -> tuple[object, RecordingImages]:
    pipeline = create_memory_runtime().pipeline
    images = RecordingImages()

    class Store:
        async def presigned_get_url(self, key, expires_in=900):
            return f'https://assets.test/{key}'

        async def put_bytes(self, object_key, content, content_type):
            return None

    pipeline._asset_store = Store()
    pipeline._reference_image_provider = images
    return pipeline, images


async def test_character_reference_default_is_a_still_neutral_sheet() -> None:
    pipeline, images = await _pipeline_with_images()
    await pipeline._generate_character_reference(
        {'id': 'c1', 'name': '小明', 'appearance': '短发', 'clothing': '校服'}, 'p1'
    )
    prompt = images.prompts[0]
    assert '漫画风格' not in prompt
    assert '全身正面' in prompt
    assert '表情' in prompt


async def test_scene_background_default_matches_the_character_style() -> None:
    pipeline, images = await _pipeline_with_images()
    await pipeline._generate_scene_background(
        {'id': 'scene1', 'location': '车站', 'time': '夜晚'}, 'p1'
    )
    prompt = images.prompts[0]
    assert '漫画风格' not in prompt
    assert '写实' in prompt
    assert '车站' in prompt and '夜晚' in prompt


def test_keyframe_provider_appends_the_vertical_instruction() -> None:
    from comicflow.providers.wanx_image import _build_prompt

    prompt = _build_prompt({
        'imagePurpose': 'scene-background', 'visualDescription': '写实电影感车站背景图',
    }, [])
    assert '写实电影感车站背景图' in prompt
    assert '9:16' in prompt


def test_keyframe_provider_does_not_force_an_anime_style() -> None:
    """The caller's style must win; a hard-coded 漫画风格 overrode it."""
    from comicflow.providers.wanx_image import _build_prompt

    for shot in (
        {'imagePurpose': 'character-reference', 'visualDescription': '写实角色参考图'},
        {'imagePurpose': 'scene-background', 'visualDescription': '写实场景背景图'},
        {'title': '镜头一', 'visualDescription': '写实画面', 'action': '走路'},
    ):
        assert '漫画' not in _build_prompt(shot, [])


def test_keyframe_prompt_uses_project_style_instead_of_fixed_photorealism() -> None:
    from comicflow.providers.wanx_image import _build_prompt

    prompt = _build_prompt({'title': '镜头一', 'visualDescription': '少女回头',
                            'visualStyle': '水墨淡彩，留白构图'}, [])
    assert '画面风格：水墨淡彩，留白构图' in prompt
    assert '真实摄影质感' not in prompt
    assert '9:16' in prompt


async def test_scene_background_prefers_the_stored_prompt() -> None:
    pipeline, images = await _pipeline_with_images()
    await pipeline._generate_scene_background(
        {'id': 'scene1', 'location': '车站', 'time': '夜晚',
         'backgroundImagePrompt': '用户自己的画面风格：雨夜车站，冷色调霓虹'}, 'p1'
    )
    assert images.prompts[0].startswith('用户自己的画面风格')
    assert '漫画风格' not in images.prompts[0]


async def test_character_reference_still_prefers_the_stored_prompt() -> None:
    pipeline, images = await _pipeline_with_images()
    await pipeline._generate_character_reference(
        {'id': 'c1', 'name': '小明', 'appearance': '短发', 'clothing': '校服',
         'referenceImagePrompt': '用户自己的角色风格：水墨画线稿'}, 'p1'
    )
    assert images.prompts[0].startswith('用户自己的角色风格')
