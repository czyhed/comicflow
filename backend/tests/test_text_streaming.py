"""One billed request, incremental content, local validation, no implicit repair."""
import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.mock import MockTextProvider
from comicflow.providers.model_protocols import TemplateTransport
from comicflow.providers.model_selection import TemplateTextProvider
from comicflow.providers.text_progress import text_progress


@pytest.mark.parametrize('template', [False, True])
@pytest.mark.parametrize('truncated', [False, True])
async def test_preview_stream_single_call_and_read_only_until_commit(template, truncated):
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，两人在车站相遇。', mode='import_story', duration_sec=30))
    pid = created['project']['id']
    script = await MockTextProvider().split_script('雨夜车站', pid, 30)
    script.update(mode='automatic', task='script_split')
    content = json.dumps(script, ensure_ascii=False)
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert body['stream'] is True
        if template:
            assert body['max_tokens'] == 16384
        frames = [{'choices': [{'delta': {'content': part}}]} for part in
                  (content[:80], content[80:])]
        frames += [{'choices': [{'delta': {}, 'finish_reason':
                                'length' if truncated else 'stop'}]}]
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            text=''.join('data: ' + json.dumps(f) + '\n\n' for f in frames)
                 + 'data: [DONE]\n\n')

    transport = httpx.MockTransport(handler)
    cls = BailianTextProvider
    if template:
        cls = TemplateTextProvider
        transport = TemplateTransport({'request': {'body': {
            'model': '{{model}}', 'messages': '{{messages}}', 'max_tokens': 16384,
        }}}, 'https://offline.invalid', 'offline', inner=transport)
    runtime.pipeline.set_text_provider(cls(api_key='offline', base_url='https://offline.invalid',
        transport=transport, max_retries=2))
    before = deepcopy(await runtime.pipeline.get_snapshot(pid))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        response = await client.post(f'/api/projects/{pid}/script/preview', json={},
                                     headers={'Accept': 'text/event-stream'})
        assert response.headers['content-type'].startswith('text/event-stream')
        events = [json.loads(line[6:]) for line in response.text.splitlines()
                  if line.startswith('data: ')]
        assert ''.join(e['delta'] for e in events if e['type'] == 'delta') == content
        assert (await runtime.pipeline.get_snapshot(pid)) == before
        assert len(calls) == 1
        if truncated:
            assert events[-1]['type'] == 'error'
            assert events[-1]['error']['reason'] == 'output_truncated'
        else:
            assert events[-1]['type'] == 'result'
            preview = events[-1]['result']
            committed = await client.put(f'/api/projects/{pid}/script/preview', json={
                'script': preview['script'], 'expectedVersion': preview['expectedVersion']})
            assert committed.status_code == 200
            assert len(calls) == 1  # Confirmation does not generate or review with a model.


async def test_invalid_story_does_not_issue_paid_repair():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'message': {
            'content': '{"kind":"story_text","version":1,"content":{"title":"过短"}}'}}]})

    provider = BailianTextProvider(api_key='offline', base_url='https://offline.invalid',
        max_retries=0, transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError):
        await provider.generate_story_text('雨夜车站', 'p', 30)
    assert len(calls) == 1


async def test_story_post_streams_once_and_preserves_repeated_deltas():
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，两人在车站相遇。', mode='automatic', duration_sec=30))
    pid = created['project']['id']
    part = '女孩在雨夜车站等待姐姐，姐姐终于出现。' * 20
    calls, moderation = [], []

    class Moderate:
        async def moderate(self, text):
            moderation.append(text)
            return {'status': 'approved'}

    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text=(
            'data: ' + json.dumps({'choices': [{'delta': {'content': part}}]}) + '\n\n'
        ) * 2 + 'data: [DONE]\n\n')

    runtime.pipeline._moderation_provider = Moderate()
    runtime.pipeline.set_text_provider(TemplateTextProvider(api_key='offline',
        base_url='https://offline.invalid', transport=TemplateTransport(
            {'request': {'body': {'model': '{{model}}', 'messages': '{{messages}}'}}},
            'https://offline.invalid', 'offline', inner=httpx.MockTransport(handle))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                base_url='http://test') as client:
        response = await client.post(f'/api/projects/{pid}/story', json={},
                                     headers={'Accept': 'text/event-stream'})
    events = [json.loads(line[6:]) for line in response.text.splitlines()
              if line.startswith('data: ')]
    assert ''.join(e['delta'] for e in events if e['type'] == 'delta') == part * 2
    assert events[-1]['result']['storyText'] == part * 2
    assert len(calls) == len(moderation) == 1


async def test_provider_delivers_partial_text_before_upstream_finishes():
    entered, release = asyncio.Event(), asyncio.Event()
    chunks = []
    calls = []
    script = await MockTextProvider().split_script('雨夜车站', 'p', 30)
    script.update(mode='automatic', task='script_split')
    raw = json.dumps(script, ensure_ascii=False)

    class GatedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield ('data: ' + json.dumps({'choices': [{'delta': {'content': raw[:100]}}]})
                   + '\n\n').encode()
            await asyncio.wait_for(release.wait(), 2)
            yield ('data: ' + json.dumps({'choices': [{'delta': {'content': raw[100:]}}]})
                   + '\n\ndata: [DONE]\n\n').encode()

    async def observe(event):
        if event['type'] == 'delta':
            chunks.append(event['delta'])
            entered.set()

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=GatedBody(),
                              headers={'content-type': 'text/event-stream'})

    provider = BailianTextProvider(api_key='offline', base_url='https://offline.invalid',
        transport=httpx.MockTransport(handle))
    token = text_progress.set(observe)
    task = asyncio.create_task(provider.split_script('故事', 'p', 30))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert not task.done()
        assert chunks == [raw[:100]]
    finally:
        release.set()
        result = await task
        text_progress.reset(token)
    assert result['title']
    assert ''.join(chunks) == raw
    assert len(calls) == 1


@pytest.mark.parametrize('custom_path', [False, True])
async def test_explicit_non_stream_template_stays_one_request(custom_path):
    script = await MockTextProvider().split_script('车站', 'p', 30)
    script.update(mode='automatic', task='script_split')
    calls, events = [], []

    def handle(request):
        calls.append(json.loads(request.content))
        assert not calls[-1].get('stream')
        text = json.dumps(script, ensure_ascii=False)
        return httpx.Response(200, json={'result': {'text': text}} if custom_path else
                              {'choices': [{'message': {'content': text}}]})

    config = {'request': {'body': {'model': '{{model}}', 'messages': '{{messages}}',
                                  'stream': False}}}
    if custom_path:
        config['responseTextPath'] = 'result.text'
        del config['request']['body']['stream']
    provider = TemplateTextProvider(api_key='offline', base_url='https://offline.invalid',
        transport=TemplateTransport(config, 'https://offline.invalid', 'offline',
                                    inner=httpx.MockTransport(handle)))

    async def observe(event):
        events.append(event)

    token = text_progress.set(observe)
    try:
        result = await provider.split_script('故事', 'p', 30)
    finally:
        text_progress.reset(token)
    assert result['title']
    assert len(calls) == 1
    assert events == [{'type': 'phase', 'phase': 'buffered'}]


async def test_disconnected_observer_does_not_restart_or_cancel_paid_work():
    from comicflow.api.text_stream import text_response
    entered, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    async def operation():
        calls.append('started')
        entered.set()
        await release.wait()
        completed.set()
        return {'saved': True}

    response = await text_response('text/event-stream', operation)
    iterator = response.body_iterator
    assert 'waiting' in await anext(iterator)
    await entered.wait()
    await iterator.aclose()
    release.set()
    await asyncio.wait_for(completed.wait(), 2)
    assert calls == ['started']
