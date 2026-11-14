import json
import socket

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.doubao_text import DoubaoTextProvider
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from test_h3_skill_execution import valid_rewrite


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def deny(*args, **kwargs):
        pytest.fail('Real sockets are prohibited')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)


@pytest.mark.parametrize('kind,reason,status', [
    ('html', 'invalid_envelope', 502),
    ('empty', 'empty_content', 502),
    ('empty_parts', 'empty_content', 502),
    ('thinking', 'reasoning_only', 502),
    ('refusal', 'content_refused', 502),
    ('filter', 'content_refused', 502),
    ('object', 'content_not_text', 502),
    ('invalid', 'invalid_json', 502),
    ('truncated', 'output_truncated', 502),
    ('network', 'connection_error', 503),
])
async def test_text_failure_is_specific_without_retry_video_or_private_output(kind, reason, status,
                                                                            caplog):
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，一个人在街上看手机。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{'id': 's6', 'durationSec': 5}]}
    await runtime.pipeline._repository.save(record)
    calls = []

    def respond(request):
        calls.append(request)
        if kind == 'network':
            raise httpx.ConnectError('private-secret', request=request)
        if kind == 'html':
            return httpx.Response(200, text='<html>private-secret</html>')
        message = {'content': ''}
        finish = 'stop'
        if kind == 'empty_parts':
            message['content'] = [{'type': 'text', 'text': ' '}]
        if kind == 'thinking':
            message['reasoning_content'] = 'private-secret'
        elif kind == 'refusal':
            message['refusal'] = 'private-secret'
        elif kind == 'filter':
            finish = 'content_filter'
        elif kind == 'object':
            message['content'] = {'private-secret': True}
        elif kind in {'invalid', 'truncated'}:
            message['content'] = 'private-secret'
            finish = 'length' if kind == 'truncated' else 'private-secret'
        return httpx.Response(200, json={
            'choices': [{'finish_reason': finish, 'message': message}],
        })

    text_provider = DoubaoTextProvider(api_key='private-secret',
                                      transport=httpx.MockTransport(respond))

    def video_request(request):
        pytest.fail('Failed expansion must not reach video provider')

    runtime.pipeline.set_text_provider(text_provider)
    runtime.pipeline.set_video_provider(MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(video_request),
        prompt_writer=H3SkillPromptWriter(text_provider.compile_h3_prompt),
    ))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s6/visual', json={
            'expectedVersion': record.project['version'],
        })
    assert response.status_code == status
    detail = response.json()
    assert detail['stage'] == 'h3_text'
    assert detail['reason'] == reason
    if kind in {'invalid', 'truncated'}:
        assert detail['contentCharacters'] == len('private-secret')
        assert detail['finishReason'] == ('length' if kind == 'truncated' else 'unknown')
    assert len(calls) == 1
    assert not (await runtime.pipeline._repository.get(pid)).project.get('visualAssets')
    assert 'private-secret' not in response.text + caplog.text


@pytest.mark.parametrize('shape', ['plain', 'fenced', 'parts'])
async def test_valid_response_still_executes_skill(shape):
    async def respond(request):
        payload = json.loads(request.content)
        result = await valid_rewrite(payload['messages'][0]['content'],
                                     payload['messages'][1]['content'])
        content = json.dumps(result)
        if shape == 'fenced':
            content = f'```json\n{content}\n```'
        if shape == 'parts':
            content = [{'type': 'text', 'text': content}]
        return httpx.Response(200, json={'choices': [{
            'finish_reason': 'stop', 'message': {'content': content},
        }]})

    provider = DoubaoTextProvider(api_key='offline', transport=httpx.MockTransport(respond))
    compiled = await H3SkillPromptWriter(provider.compile_h3_prompt).write(
        {'id': 's6', 'durationSec': 5, 'narration': '夜色笼罩街道。'}, [],
    )
    assert '<d>[Chinese] 夜色笼罩街道。</d>' in compiled['prompt']
    assert compiled['execution']['skill'] == 'h3-prompt-writing'
