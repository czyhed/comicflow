"""Style content must reach media requests without changing authored inputs."""
import base64
import json
from copy import deepcopy

import httpx
import pytest
from comicflow.production.visual_styles import apply_video_style, resolve_style
from comicflow.providers.drama_skills import prepare_visual_asset_request
from comicflow.providers.h3_context_ir import compile_chinese_intent
from comicflow.providers.openai_image import OpenAIImageProvider


@pytest.mark.parametrize('preset', [
    'documentary-dv', 'suspense-realism', 'cinematic-color-contrast', 'hong-kong-wuxia-film',
])
def test_live_action_styles_preserve_authored_shot_and_reference_clarity(preset):
    profile = resolve_style(preset)
    shot = {'id': 's1', 'durationSec': 6, 'visualDescription': '女子在晴天推门进入店铺',
            'dialogue': '你好。', 'narration': '', 'soundscape': '脚步声',
            'scene': {'location': '店铺', 'time': '白天'}}
    before = deepcopy(shot)
    prepared = apply_video_style(shot, {'visualStyleProfile': profile})
    assert shot == before
    for key in ('durationSec', 'dialogue', 'narration', 'soundscape'):
        assert prepared[key] == shot[key]
    assert profile['name'] in compile_chinese_intent(prepared, [])['prompt']
    image = prepare_visual_asset_request({'imagePurpose': 'character-reference',
        'visualDescription': '短发蓝衣女子', 'styleSnapshot': profile})
    assert profile['rendering'] in image['visualDescription']
    assert '光线均匀便于辨认' in image['visualDescription']
    assert profile['motion'] not in image['visualDescription']


@pytest.mark.parametrize('model', ['gpt-image-2', 'gpt-image-2.5'])
@pytest.mark.parametrize('preset', ['anime-2d', 'cinematic-realism', 'hong-kong-wuxia-film'])
async def test_image_model_alias_does_not_override_project_style(model, preset):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        content = base64.b64encode(b'local-image-fixture' * 10).decode()
        return httpx.Response(200, json={'choices': [{'message': {
            'content': f'![image](data:image/png;base64,{content})'}}]})

    profile = resolve_style(preset)
    request = prepare_visual_asset_request({'id': 'offline',
        'imagePurpose': 'character-reference', 'visualDescription': '短发蓝衣女子',
        'styleSnapshot': profile})
    provider = OpenAIImageProvider(api_key='offline-only', base_url='https://offline.invalid',
        model=model, transport=httpx.MockTransport(handle))
    await provider.generate(request, [])
    assert len(requests) == 1
    assert requests[0]['model'] == model
    prompt = requests[0]['messages'][0]['content']
    assert profile['rendering'] in prompt
    assert '短发蓝衣女子' in prompt
    for imposed in ('ultra-realistic 3D render', '8K resolution', 'visible pores',
                    'Unreal Engine 5', 'no film grain'):
        assert imposed not in prompt
