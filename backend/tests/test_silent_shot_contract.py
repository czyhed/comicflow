"""A sound-only shot must reach H3 without invented spoken narration."""

import json
from copy import deepcopy

import httpx
import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.production.script_preview import normalize_preview
from comicflow.providers.bailian_text import BailianTextProvider, _script_prompt
from comicflow.providers.xiangongyun_h3 import XiangongyunH3Provider
from test_script_preview_lines import _script, _shot
from test_script_preview_response_validation import preview, script

SOUNDS = '暴雨声、车门气动声、雨点敲打车顶声'


def test_script_instructions_allow_explicit_no_speech_without_sound_as_narration():
    prompt = _script_prompt(30, mode='import_story', task='script_split')
    assert '至少一项非空' not in prompt
    assert '无对白和旁白时两项都输出空字符串' in prompt


@pytest.mark.parametrize('template', [False, True])
async def test_real_adapter_preview_accepts_explicit_sound_only_shot(template):
    envelope = script()
    envelope['content']['shots'][0].update(dialogue='', narration='', soundscape=SOUNDS)
    response = await preview(
        {'choices': [{'message': {'content': json.dumps(envelope)}}]}, template=template,
    )
    assert response.status_code == 200, response.text
    first = response.json()['script']['shots'][0]
    assert first['dialogue'] == first['narration'] == ''
    assert first['soundscape'] == SOUNDS


async def test_sound_only_edit_can_be_confirmed_and_keeps_prior_script_and_video():
    runtime = create_memory_runtime()
    p = runtime.pipeline
    created = await p.create_project(CreateProject(
        input_type='story', story='年轻人在暴雨中赶上最后一班公交车。',
        duration_sec=30, mode='import_story'))
    pid = created['project']['id']
    record = await p._repository.get(pid)
    original = _script([_shot('s1', dialogue='', narration=SOUNDS, soundscape=SOUNDS)])
    record.project['script'] = original
    record.project['visualAssets'] = [
        {'id': 'prior-video', 'shotId': 's1', 'valid': True, 'objectKey': 'prior.mp4'},
    ]
    await p._repository.save(record)
    corrected = deepcopy(original)
    corrected['shots'][0]['narration'] = ''
    normalized = normalize_preview(corrected, target_duration_sec=30)
    BailianTextProvider._validate_split_script(normalized, target_duration_sec=30)
    updated = await p.update_script(pid, normalized, expected_version=record.project['version'])
    confirmed = await p.confirm_script(pid, expected_version=updated['project']['version'])
    assert confirmed['project']['stage'] == 'storyboard-ready'
    saved = (await p._repository.get(pid)).project
    assert saved['scriptVersions'][0]['script'] == original
    assert saved['visualAssets'][0]['objectKey'] == 'prior.mp4'
    assert saved['visualAssets'][0]['valid'] is False
    assert saved['script']['shots'][0]['narration'] == ''
    assert saved['script']['shots'][0]['soundscape'] == SOUNDS


async def test_h3_multipart_keeps_environment_sound_out_of_spoken_section():
    calls = []

    def handle(request):
        calls.append(request)
        if request.method == 'POST':
            body = request.content.decode()
            spoken = body.split('【台词】')[1].split('【声音】')[0]
            assert SOUNDS not in spoken
            assert '无对白、无旁白，不新增人声' in spoken
            assert '环境声：' + SOUNDS in body
            return httpx.Response(202, json={'data': {'prompt_id': 'silent-1'}})
        if request.url.path == '/api/v1/jobs/silent-1':
            return httpx.Response(200, json={'data': {
                'status': 'completed', 'terminal': True, 'succeeded': True,
                'outputs': [{'download_url': '/api/v1/output?filename=silent.mp4'}],
            }})
        return httpx.Response(200, content=b'fake-video', headers={'content-type': 'video/mp4'})

    provider = XiangongyunH3Provider(
        api_key='offline', base_url='https://offline.test', transport=httpx.MockTransport(handle),
    )
    await provider.generate(_shot('s1', dialogue='', narration='', soundscape=SOUNDS), [])
    assert len([r for r in calls if r.method == 'POST']) == 1
