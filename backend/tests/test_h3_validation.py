import json

import httpx
import pytest
from comicflow.providers.h3_skill import H3SkillPromptWriter


def rewrite(description):
    return {'durationSec': 5, 'sections': {
        'integrated_multimodal_description': description,
        'overall_soundscape': 'Footsteps in a hallway.', 'non_diegetic_music': 'N/A',
    }}


@pytest.mark.parametrize('mode,extras', [
    ('i2va', {'firstFrameUrl': 'https://assets.test/first.png'}),
    ('l2va', {'lastFrameUrl': 'https://assets.test/last.png'}),
    ('fl2va', {'firstFrameUrl': 'https://assets.test/first.png',
              'lastFrameUrl': 'https://assets.test/last.png'}),
])
async def test_keyframe_alignment_is_supplied_by_writer_not_required_in_body(mode, extras):
    calls = []

    async def complete(system, user):
        calls.append(json.loads(user))
        return rewrite('[Shot 1] A student runs toward a vending machine.')

    result = await H3SkillPromptWriter(complete).write({
        'durationSec': 5, 'generationMode': mode, **extras,
    }, [])
    assert len(calls) == 1
    assert 'Picture 1' in result['prompt']
    assert ('Picture 2' in result['prompt']) == (mode == 'fl2va')


async def test_multiline_dialogue_can_be_split_into_ordered_speech_blocks():
    async def complete(system, user):
        return rewrite('[Shot 1] He says <d>[Chinese] 等一下！</d> '
                       'He pauses, then says <d>[Chinese] 我来了。</d>')

    result = await H3SkillPromptWriter(complete).write({
        'durationSec': 5, 'dialogue': '等一下！\n我来了。',
    }, [])
    assert '等一下！' in result['prompt']


@pytest.mark.parametrize('problem,reason', [
    ('duration', 'duration'), ('sections', 'sections'), ('shot', 'shots'),
    ('language', 'language'), ('labels', 'references'),
    ('subjects', 'subjects'), ('timing', 'timing'),
])
async def test_invalid_rewrite_reports_safe_reason(problem, reason, caplog):
    async def complete(system, user):
        result = rewrite('[Shot 1] A student runs.')
        sections = result['sections']
        if problem == 'duration':
            result['durationSec'] = 6
        elif problem == 'sections':
            sections.pop('overall_soundscape')
        elif problem == 'shot':
            sections['integrated_multimodal_description'] = 'Missing shot marker.'
        elif problem == 'language':
            sections['integrated_multimodal_description'] += ' 私密画面描述'
        elif problem == 'labels':
            sections['integrated_multimodal_description'] += ' <Picture 9>'
        elif problem == 'subjects':
            sections['integrated_multimodal_description'] += ' <Subject 1>'
        elif problem == 'timing':
            sections['integrated_multimodal_description'] += ' At 00:06.000 the camera cuts.'
        return result

    with pytest.raises(RuntimeError, match='^H3_PROMPT_INVALID$') as error:
        await H3SkillPromptWriter(complete).write({'durationSec': 5}, [])
    assert error.value.reason == reason
    assert f'reason={reason}' in caplog.text
    assert '私密' not in caplog.text


async def test_missing_reference_is_not_relaxed():
    async def complete(system, user):
        return {'durationSec': 5, 'sections': {
            'subject_definitions': '<Subject 1> is a student.',
            'summary': '<Subject 1> runs.', 'retention_analysis': 'Preserve the uniform.',
            'detailed_description': '[Shot 1] <Subject 1> runs.',
            'overall_soundscape': 'Footsteps.', 'non_diegetic_music': 'N/A',
        }}

    characters = [{'id': 'c1', 'referenceImageUrl': 'https://assets.test/c.png'}]
    with pytest.raises(RuntimeError, match='H3_PROMPT_INVALID'):
        await H3SkillPromptWriter(complete).write({'durationSec': 5}, characters)


@pytest.mark.parametrize('reason', ['narration', 'language'])
async def test_h3_reason_reaches_api_without_video_submission_or_source_leak(reason):
    from comicflow.api.app import create_app
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime
    from comicflow.providers.minimax_h3 import MinimaxH3Provider

    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='一个学生在走廊里跑向自动售货机。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{
        'id': 's1', 'durationSec': 5, 'narration': '私密旁白', 'characterIds': [],
    }]}
    await runtime.pipeline._repository.save(record)
    text_calls = []

    async def complete(system, user):
        text_calls.append(1)
        if reason == 'language':
            return rewrite('[Shot 1] 私密画面描述')
        return rewrite('[Shot 1] A student runs.')

    submitted = []

    def handler(request):
        if request.method == 'POST':
            submitted.append(json.loads(request.content)['content'][0]['text'])
            return httpx.Response(200, json={'task_id': 'offline'})
        if '/query/' in request.url.path:
            return httpx.Response(200, json={
                'task': {'status': 'succeeded', 'content': {'url': 'https://assets.test/out.mp4'}},
            })
        return httpx.Response(200, content=b'offline-test-only')

    provider = MinimaxH3Provider(
        api_key='offline', transport=httpx.MockTransport(handler),
        asset_store=None,
    )
    runtime.pipeline.set_video_provider(provider)
    provider.set_prompt_writer(H3SkillPromptWriter(complete))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url='http://test',
    ) as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/visual', json={
            'expectedVersion': record.project['version'],
        })
    assert text_calls == [1]
    if reason == 'language':
        # Rejected before any paid video submission, and the reason stays generic.
        assert response.status_code == 502
        assert response.json() == {
            'error': 'H3_PROMPT_INVALID', 'reason': 'language',
            'section': 'integrated_multimodal_description',
        }
        assert submitted == []
        assert not (await runtime.pipeline._repository.get(pid)).project.get('visualAssets')
    else:
        # The narration line the model never wrote is injected verbatim instead of
        # rejecting an expansion the user already paid for.
        assert response.status_code == 200, response.text
        assert '<d>[Chinese] 私密旁白</d>' in submitted[0]
