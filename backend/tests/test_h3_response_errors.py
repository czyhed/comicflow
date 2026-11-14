import json

import httpx
import pytest
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.h3_skill import H3SkillPromptWriter
from comicflow.providers.minimax_h3 import MinimaxH3Provider
from test_h3_skill_execution import valid_rewrite


@pytest.mark.parametrize('phase', ['h3_submit', 'h3_poll', 'h3_result'])
async def test_h3_bad_response_identifies_phase_without_resubmitting(phase, caplog):
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json=({'unexpected': 'private-secret'}
                if phase == 'h3_submit' else {'task_id': 'known-task-123'}))
        if phase == 'h3_poll':
            return httpx.Response(200, content=b'not-json-private-secret')
        return httpx.Response(200, json={'task': {'status': 'succeeded'}})

    provider = MinimaxH3Provider(
        api_key='private-key', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(valid_rewrite), poll_interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match='^PROVIDER_RESPONSE_INVALID$') as error:
        await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert error.value.stage == phase
    assert error.value.task_id == (None if phase == 'h3_submit' else 'known-task-123')
    assert calls.count('POST') == 1
    assert f'stage={phase}' in caplog.text
    assert 'private' not in caplog.text


async def test_known_task_response_error_reaches_api_without_saving_asset():
    from comicflow.api.app import create_app
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='一个学生跑向走廊里的售货机。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{'id': 's1', 'durationSec': 5}]}
    await runtime.pipeline._repository.save(record)
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'existing-task-1'})
        return httpx.Response(200, content=b'private-invalid-body')

    provider = MinimaxH3Provider(api_key='private', transport=httpx.MockTransport(handler))
    runtime.pipeline.set_video_provider(provider)
    provider.set_prompt_writer(H3SkillPromptWriter(valid_rewrite))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })
    assert response.status_code == 502
    assert response.json() == {
        'error': 'PROVIDER_INVALID_RESPONSE', 'stage': 'h3_poll',
        'reason': 'invalid_response', 'taskId': 'existing-task-1',
    }
    assert calls == ['POST', 'GET']
    assert not (await runtime.pipeline._repository.get(pid)).project.get('visualAssets')


@pytest.mark.parametrize('body,upstream_code', [
    ({'type': 'error', 'error': {
        'type': 'bad_request_error', 'message': 'private prompt detail', 'http_code': '400',
    }, 'request_id': 'private-request'}, 'bad_request_error'),
    ({'RetCode': 1002, 'Message': 'private downstream detail',
      'request_uuid': 'private-request'}, '1002'),
])
async def test_h3_http_200_business_rejection_is_not_reported_as_uncertain_task(
    body, upstream_code, caplog,
):
    from comicflow.api.app import create_app
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='雨夜，一个人走进店内。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{'id': 's1', 'durationSec': 5}]}
    await runtime.pipeline._repository.save(record)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    provider = MinimaxH3Provider(
        api_key='private', transport=httpx.MockTransport(handler),
    )
    runtime.pipeline.set_video_provider(provider)
    provider.set_prompt_writer(H3SkillPromptWriter(valid_rewrite))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })
    assert response.status_code == 400
    assert response.json() == {
        'error': 'VIDEO_REQUEST_INVALID', 'stage': 'h3_submit',
        'reason': 'business_rejected', 'upstreamStatus': 400,
        'upstreamCode': upstream_code,
    }
    assert len(calls) == 1
    saved = (await runtime.pipeline.list_video_jobs(pid))[0]
    expected_key = f"comicflow-{saved['id']}"
    assert calls[0].headers.get('idempotency-key') == expected_key
    assert 'private' not in response.text + caplog.text


async def test_h3_prompt_over_official_limit_is_rejected_before_video_submit():
    video_calls = []

    async def oversized_rewrite(system_prompt, input_text):
        result = await valid_rewrite(system_prompt, input_text)
        result['sections']['integrated_multimodal_description'] = '[Shot 1] ' + 'x' * 7001
        return result

    provider = MinimaxH3Provider(
        api_key='private',
        transport=httpx.MockTransport(lambda request: video_calls.append(request)),
        prompt_writer=H3SkillPromptWriter(oversized_rewrite),
    )
    with pytest.raises(RuntimeError, match='^VIDEO_PROMPT_TOO_LONG$'):
        await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert video_calls == []


async def test_h3_http_200_poll_rejection_preserves_created_task_id():
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'known-task-1'})
        return httpx.Response(200, json={
            'type': 'error',
            'error': {'type': 'service_error', 'message': 'private', 'http_code': '503'},
        })

    provider = MinimaxH3Provider(
        api_key='private', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(valid_rewrite), poll_interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match='^PROVIDER_HTTP_ERROR$') as error:
        await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert error.value.detail == {
        'stage': 'h3_poll', 'reason': 'service_error', 'upstreamStatus': 503,
        'upstreamCode': 'service_error', 'taskId': 'known-task-1',
    }
    assert calls == ['POST', 'GET']


@pytest.mark.parametrize('status,reason,api_status,domain', [
    (429, 'rate_limited', 429, 'PROVIDER_RATE_LIMITED'),
    (400, 'invalid_parameter', 400, 'PROVIDER_REQUEST_INVALID'),
])
async def test_refused_h3_prompt_text_call_names_its_stage_and_reason(
    status, reason, api_status, domain, caplog,
):
    """A refused H3 prompt text call must not look like a failed video.

    Every text refusal used to collapse into the generic provider default, so a
    shot whose video was never submitted was reported as an unreachable
    provider. The refusal has to name the stage and the closed-set reason.
    """
    from comicflow.api.app import create_app
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime
    from comicflow.providers.doubao_text import DoubaoTextProvider

    text_calls, video_calls = [], []

    def text_handler(request):
        text_calls.append(request)
        return httpx.Response(status, json={'error': {
            'code': 'InvalidParameter' if status == 400 else 'anything',
            'param': 'model',
            'message': 'secret-key https://private.test/?signature=private',
        }})

    def video_handler(request):
        video_calls.append(request.method)
        return httpx.Response(200, json={'task_id': 'never-submitted'})

    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(DoubaoTextProvider(
        api_key='secret-key', transport=httpx.MockTransport(text_handler),
    ))
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='一个学生跑向走廊里的售货机。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{'id': 's1', 'durationSec': 5}]}
    await runtime.pipeline._repository.save(record)
    runtime.pipeline.set_video_provider(MinimaxH3Provider(
        api_key='private', transport=httpx.MockTransport(video_handler),
    ))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })

    assert response.status_code == api_status
    assert response.json() == {
        'error': domain, 'stage': 'h3_text', 'upstreamStatus': status,
        'reason': reason, 'parameter': 'model',
    }
    assert len(text_calls) == 1
    assert video_calls == []
    assert not (await runtime.pipeline._repository.get(pid)).project.get('visualAssets')
    assert 'secret-key' not in response.text
    assert 'private.test' not in response.text
    assert 'stage=h3_text' in caplog.text
    assert f'upstream_status={status}' in caplog.text
    assert 'secret-key' not in caplog.text


async def test_a_timed_out_h3_prompt_reports_the_budget_it_ran_out_of():
    """A text timeout must say which stage timed out and what the budget was.

    The H3 prompt carries the whole Skill rule set, so it can outlast a budget
    that a one-token connectivity ping sails through. Saying only "timed out"
    leaves the operator with no idea which knob to turn.
    """
    from comicflow.api.app import create_app
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime
    from comicflow.providers.doubao_text import DoubaoTextProvider

    def text_handler(request):
        raise httpx.TimeoutException("too slow")

    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(DoubaoTextProvider(
        api_key='secret-key', timeout_seconds=45,
        transport=httpx.MockTransport(text_handler),
    ))
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='一个学生跑向走廊里的售货机。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{'id': 's1', 'durationSec': 5}]}
    await runtime.pipeline._repository.save(record)
    runtime.pipeline.set_video_provider(MinimaxH3Provider(
        api_key='private', transport=httpx.MockTransport(httpx.Response(500)),
    ))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })

    assert response.status_code == 504
    assert response.json() == {
        'error': 'PROVIDER_TIMEOUT', 'stage': 'h3_text', 'reason': 'timeout',
        'timeoutMs': 45000,
    }


@pytest.mark.parametrize('body,reason', [
    ({'choices': []}, 'message_missing'),
    ({'choices': [{'finish_reason': 'length', 'message': {'content': '{"sections":'}}]},
     'output_truncated'),
    ({'choices': [{'message': {'content': 'not-json-private'}}]}, 'invalid_json'),
])
async def test_h3_text_invalid_response_is_not_video_failure(body, reason, caplog):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    text = BailianTextProvider(api_key='private', base_url='https://text.test/v1',
                              transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match='^PROVIDER_RESPONSE_INVALID$') as error:
        await text.compile_h3_prompt('Skill', 'shot')
    assert error.value.stage == 'h3_text'
    assert error.value.reason == reason
    assert len(calls) == 1
    assert 'private' not in caplog.text


async def test_unrecognised_poll_status_keeps_polling_instead_of_dropping_the_task(
    caplog,
):
    """A submitted task must survive a status value we do not recognise yet.

    Failing on the first unfamiliar status loses a task the user already paid
    for, and the response itself is the only chance to learn that status.
    """
    statuses = iter(['Uploading', 'succeeded'])

    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'known-task-1'})
        if '/query/' not in request.url.path:
            return httpx.Response(200, content=b'offline-test-only')
        return httpx.Response(200, json={
            'task': {'status': next(statuses), 'content': {'url': 'https://assets.test/out.mp4'}},
        })

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(valid_rewrite), poll_interval_seconds=0,
    )
    result = await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert result['mediaType'] == 'video'
    assert 'status=Uploading' in caplog.text


def test_status_diagnostics_stay_inside_a_safe_token():
    from comicflow.providers.minimax_h3 import safe_status_token

    assert safe_status_token('Uploading') == 'Uploading'
    assert safe_status_token('in_queue-2') == 'in_queue-2'
    assert safe_status_token('https://x.test/a?Signature=private') is None
    assert safe_status_token('x' * 80) == 'x' * 32
    assert safe_status_token(None) is None
    assert safe_status_token(12345) is None


async def test_unrecognised_status_never_leaks_upstream_detail(caplog):
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'known-task-1'})
        return httpx.Response(200, json={
            'task': {'status': 'https://x.test/a?Signature=private-secret'},
        })

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(valid_rewrite), poll_interval_seconds=0,
        timeout_seconds=0.05,
    )
    with pytest.raises(RuntimeError, match='^PROVIDER_RESPONSE_INVALID$') as error:
        await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert error.value.stage == 'h3_poll'
    assert error.value.reason == 'unknown_status'
    assert error.value.task_id == 'known-task-1'
    assert 'private' not in caplog.text


async def test_a_task_that_never_settles_reports_timeout_not_invalid_response():
    def handler(request):
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'known-task-1'})
        return httpx.Response(200, json={'task': {'status': 'running'}})

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(valid_rewrite), poll_interval_seconds=0,
        timeout_seconds=0.05,
    )
    with pytest.raises(RuntimeError, match='^PROVIDER_RESPONSE_INVALID$') as error:
        await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert error.value.stage == 'h3_poll'
    assert error.value.reason == 'timeout'
    assert error.value.task_id == 'known-task-1'


async def test_a_poll_body_that_is_not_json_is_still_a_hard_failure():
    """A body we cannot parse at all is a protocol break, not a slow task."""
    calls = []

    def handler(request):
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'task_id': 'known-task-1'})
        return httpx.Response(200, content=b'private-invalid-body')

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        prompt_writer=H3SkillPromptWriter(valid_rewrite), poll_interval_seconds=0,
    )
    with pytest.raises(RuntimeError, match='^PROVIDER_RESPONSE_INVALID$') as error:
        await provider.generate({'id': 's1', 'durationSec': 5}, [])
    assert error.value.reason == 'invalid_response'
    assert calls == ['POST', 'GET']
