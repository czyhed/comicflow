"""No-network contract tests for Chinese input and platform Context-IR."""
import json
import socket

import httpx
import pytest
import pytest_asyncio
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.h3_errors import H3PromptLengthError
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from test_h3_skill_execution import valid_rewrite


@pytest_asyncio.fixture(autouse=True)
async def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail('Real sockets forbidden: no paid generation in these tests')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)


def transport_for(calls, status=200):
    def handler(request):
        calls.append(request)
        if request.method == 'POST':
            return httpx.Response(status, json={'task_id': 'offline-task'})
        if '/query/' in request.url.path:
            return httpx.Response(200, json={'status': 'succeeded',
                                           'video_url': 'https://asset.test/video.mp4'})
        assert 'authorization' not in request.headers
        return httpx.Response(200, content=b'offline-video')
    return httpx.MockTransport(handler)


async def forbidden_writer(*args):
    pytest.fail('Context-IR must not spend local text quota')


async def test_chinese_reference_submit_preserves_action_speech_and_all_images():
    calls = []
    provider = MinimaxH3Provider(
        api_key='offline', prompt_mode='context-ir',
        prompt_writer=H3SkillPromptWriter(forbidden_writer), transport=transport_for(calls),
    )
    shot = {
        'id': 's2', 'durationSec': 5, 'visualDescription': '小林推门走进便利店。',
        'actionBefore': '站在门外', 'actionMiddle': '握住把手推开玻璃门',
        'actionAfter': '双脚与身体完全进入店内', 'dialogue': '小林：老板，还有热饭吗？',
        'narration': '雨还在下。', 'scene': {'location': '便利店', 'time': '夜晚'},
        'visualStyle': '低饱和冷蓝色调，柔和侧光', 'cameraMovement': '固定机位',
        'referenceImages': [
            {'url': 'https://asset.test/tail.png?sig=secret', 'view': 'continuity-anchor'},
            {'url': 'https://asset.test/store.png', 'view': 'scene-anchor'},
        ],
        'h3Prompt': 'Stale English must not be reused.',
    }
    characters = [{'id': 'c1', 'name': '小林', 'appearance': '黑色短发',
                   'referenceBoardUrl': 'https://asset.test/board.png'}]
    asset = await provider.generate(shot, characters)
    payload = json.loads(calls[0].content)
    assert payload['use_context_ir'] is True
    assert payload['resolution'] == '768P'
    assert payload['duration'] == 5
    assert len(payload['content']) == 4
    assert all(item['role'] == 'reference_image' for item in payload['content'][1:])
    prompt = payload['content'][0]['text']
    for text in ('小林', '站在门外', '握住把手推开玻璃门', '双脚与身体完全进入店内',
                 '黑色短发', '便利店', '低饱和冷蓝色调，柔和侧光', '固定机位',
                 '<Picture 1>', '<Picture 2>', '<Picture 3>'):
        assert text in prompt
    assert prompt.count(shot['dialogue']) == 1
    assert prompt.count(shot['narration']) == 1
    assert 'Stale English' not in prompt
    assert 'https://' not in prompt and 'sig=secret' not in prompt
    assert asset['h3Prompt'] == prompt
    assert asset['promptExecution']['mode'] == 'context-ir'
    assert asset['promptExecution']['localTextCall'] is False
    assert 'skillSha256' not in asset['promptExecution']
    assert 'sig=secret' not in json.dumps(asset['promptExecution'])
    assert sum(r.method == 'POST' for r in calls) == 1


@pytest.mark.parametrize('frames,mode,roles', [
    ({}, 't2va', []),
    ({'firstFrameUrl': 'https://asset.test/first.png'}, 'i2va', ['first_frame']),
    ({'lastFrameUrl': 'https://asset.test/last.png'}, 'l2va', ['last_frame']),
    ({'firstFrameUrl': 'https://asset.test/first.png',
      'lastFrameUrl': 'https://asset.test/last.png'}, 'fl2va', ['first_frame', 'last_frame']),
])
async def test_context_ir_needs_no_local_writer_and_preserves_keyframe_roles(frames, mode, roles):
    calls = []
    provider = MinimaxH3Provider(api_key='offline', prompt_mode='context-ir',
                                 transport=transport_for(calls))
    asset = await provider.generate({'id': 's1', 'visualDescription': '人物走向窗边',
                                     'durationSec': 5, **frames}, [])
    assert asset['generationMode'] == mode
    payload = json.loads(calls[0].content)
    assert [item['role'] for item in payload['content'][1:]] == roles
    assert '无对白、无旁白' in payload['content'][0]['text']


@pytest.mark.parametrize('shot,error', [
    ({'durationSec': 3}, 'H3_DURATION_INVALID'),
    ({'firstFrameUrl': 'http://127.0.0.1/frame.png'}, 'H3_REFERENCE_UNREACHABLE'),
    ({'firstFrameUrl': 'https://asset.test/a.png',
      'referenceImages': [{'url': 'https://asset.test/b.png'}]}, 'H3_REFERENCE_MODE_CONFLICT'),
])
async def test_context_ir_invalid_inputs_never_submit(shot, error):
    calls = []
    provider = MinimaxH3Provider(api_key='offline', prompt_mode='context-ir',
                                 transport=transport_for(calls))
    with pytest.raises(RuntimeError, match=error):
        await provider.generate({'id': 's1', 'visualDescription': '人物走向窗边', **shot}, [])
    assert calls == []


async def test_context_ir_long_chinese_refused_before_any_paid_request():
    calls = []
    provider = MinimaxH3Provider(api_key='offline', prompt_mode='context-ir',
                                 transport=transport_for(calls))
    with pytest.raises(H3PromptLengthError) as exc:
        await provider.generate({'id': 's1', 'visualDescription': '雨' * 7001}, [])
    assert exc.value.detail['textExpansionAttempted'] is False
    assert calls == []


async def test_context_ir_empty_intent_cannot_spend_video_quota():
    calls = []
    provider = MinimaxH3Provider(api_key='offline', prompt_mode='context-ir',
                                 transport=transport_for(calls))
    with pytest.raises(RuntimeError, match='VIDEO_PROMPT_REQUIRED'):
        await provider.generate({'id': 's1', 'h3Prompt': 'old prompt'}, [])
    assert calls == []


async def test_context_ir_local_reference_is_validated_and_encoded_before_submission():
    from test_h3_preflight import png

    class Store:
        async def get_bytes(self, key, max_bytes):
            return png()

        async def put_bytes(self, **kwargs):
            pass

    calls = []
    provider = MinimaxH3Provider(api_key='offline', prompt_mode='context-ir',
                                 asset_store=Store(), transport=transport_for(calls))
    await provider.generate({'id': 's1', 'visualDescription': '人物走向窗边',
                             'firstFrameUrl': 'http://127.0.0.1/frame.png',
                             'firstFrameObjectKey': 'frame.png'}, [])
    payload = json.loads(calls[0].content)
    assert payload['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert 'base64' not in payload['content'][0]['text']


async def test_environment_helper_preserves_opt_in_and_default(monkeypatch):
    from comicflow.providers.minimax_h3 import minimax_config_from_env

    monkeypatch.setattr('comicflow.providers.minimax_h3._load_project_env', lambda: None)
    monkeypatch.delenv('MINIMAX_PROMPT_MODE', raising=False)
    assert minimax_config_from_env()['prompt_mode'] == 'local-skill'
    monkeypatch.setenv('MINIMAX_PROMPT_MODE', 'context-ir')
    assert minimax_config_from_env()['prompt_mode'] == 'context-ir'


async def test_context_ir_refusal_no_retry_or_english_fallback():
    calls = []
    provider = MinimaxH3Provider(
        api_key='offline', prompt_mode='context-ir',
        prompt_writer=H3SkillPromptWriter(forbidden_writer), transport=transport_for(calls, 429),
    )
    with pytest.raises(RuntimeError):
        await provider.generate({'id': 's1', 'visualDescription': '雨中车站'}, [])
    assert len(calls) == 1


async def test_prompt_mode_changes_idempotency_but_same_mode_remains_stable():
    calls = []
    shot = {'id': 's1', 'visualDescription': '雨中车站', 'providerIdempotencyKey': 'stable-key'}
    for mode in ('local-skill', 'context-ir', 'context-ir'):
        provider = MinimaxH3Provider(
            api_key='offline', prompt_mode=mode,
            prompt_writer=H3SkillPromptWriter(valid_rewrite), transport=transport_for(calls),
        )
        await provider.generate(shot, [])
    submissions = [r for r in calls if r.method == 'POST']
    assert json.loads(submissions[0].content).get('use_context_ir', False) is False
    keys = [r.headers['Idempotency-Key'] for r in submissions]
    assert keys[0] != keys[1] == keys[2]


async def test_console_roundtrip_switches_modes_without_text_or_generation():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                 base_url='http://test') as client:
        path = '/api/provider-config/profiles/video/production'
        config = {'provider': 'compshare-h3', 'baseUrl': 'https://h3.test',
                  'model': 'MiniMax-H3', 'timeoutMs': 600000, 'enabled': True,
                  'apiKey': 'offline', 'resolution': '768P', 'h3PromptMode': 'context-ir'}
        response = await client.put(path, json=config)
        assert response.status_code == 200, response.text
        view = (await client.get('/api/provider-config')).json()
        assert view['video']['h3PromptMode'] == 'context-ir'
        assert 'Context-IR' in view['runtime']['h3Prompt']
        assert 'offline' not in str(view)
        config['h3PromptMode'] = 'invalid'
        assert (await client.put(path, json=config)).status_code == 400
        view = (await client.get('/api/provider-config')).json()
        assert view['video']['h3PromptMode'] == 'context-ir'
        config['h3PromptMode'] = 'local-skill'
        assert (await client.put(path, json=config)).status_code == 200
        view = (await client.get('/api/provider-config')).json()
        assert 'h3-prompt-writing' in view['runtime']['h3Prompt']


async def test_chinese_compiler_revision_does_not_reuse_old_submission(monkeypatch):
    calls = []
    provider = MinimaxH3Provider(api_key='offline', prompt_mode='context-ir',
                                 transport=transport_for(calls))
    shot = {'id': 's1', 'visualDescription': '雨中车站', 'providerIdempotencyKey': 'stable'}
    for revision in (1, 2, 2):
        monkeypatch.setattr('comicflow.providers.h3_context_ir.COMPILER_VERSION', revision)
        await provider.generate(shot, [])
    keys = [r.headers['Idempotency-Key'] for r in calls if r.method == 'POST']
    assert keys[0] != keys[1] == keys[2]
