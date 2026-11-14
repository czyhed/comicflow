"""Frozen synthetic inputs captured before the video module extraction.

These compare observable preparation output, not the new module's implementation.
No credentials, business projects, network requests or model responses are needed.
"""
import json
from pathlib import Path

import httpx
import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
from comicflow.providers.minimax_h3 import MinimaxH3Provider

CASES = (
    'h3-first', 'h3-reanchor', 'h3-strict', 'h3-explicit', 'h3-missing-tail',
    'h3-local-skill', 'wan-single', 'wan-multiple', 'wan-existing', 'wan-text', 'mock',
)
FIXTURE = Path(__file__).parent / 'fixtures' / 'video-preparation-contract.json'


class ReferenceStore:
    async def presigned_get_url(self, key, expires_in=900):
        return f'https://assets.example.test/{key}?signature=offline'

    async def exists(self, key):
        return True


async def capture_preparation(case):
    p = create_memory_runtime().pipeline
    created = await p.create_project(CreateProject(
        input_type='story', story='雨夜，林青推门进入便利店，看见店员陈明。',
        duration_sec=30, mode='import_story'))
    record = await p._repository.get(created['project']['id'])
    record.project['id'] = pid = 'prj_offline_contract'
    record.project['version'] = version = 3
    cards = [
        {'id': 'qing', 'name': '林青', 'appearance': '短发，圆脸', 'clothing': '蓝色外套',
         'personality': '沉稳', 'voice': {}, 'revision': 2,
         'referenceImageObjectKey': 'qing-main.png',
         'referenceBoard': {'id': 'qing-board', 'objectKey': 'qing-board.png',
                            'sourceReferenceId': 'qing-main', 'createdAt': '2026-01-01'}},
        {'id': 'ming', 'name': '陈明', 'appearance': '短发，方脸', 'clothing': '灰色店员服',
         'personality': '耐心', 'voice': {}, 'revision': 1,
         'referenceImageObjectKey': 'ming-main.png'},
    ]
    for card in cards:
        await p._character_repository.save(card)
    current = {
        'id': 's2', 'title': '推门入室', 'sceneId': 'scene', 'durationSec': 5,
        'characterIds': ['qing', 'ming'], 'visualDescription': '林青推门走进便利店。',
        'action': '推门进入', 'actionBefore': '林青在门外', 'actionAfter': '林青站在店内',
        'dialogue': '你终于来了。', 'resolution': '2K', 'aspectRatio': '9:16',
    }
    previous = {'id': 's1', 'sceneId': 'scene', 'durationSec': 5, 'characterIds': ['qing']}
    cascade = case in {'h3-reanchor', 'h3-strict', 'h3-explicit', 'h3-missing-tail'}
    record.project['script'] = {
        'shots': [previous, current] if cascade else [current],
        'scenes': [{'id': 'scene', 'title': '便利店',
                    'shotIds': ['s1', 's2'] if cascade else ['s2'],
                    'backgroundImageObjectKey': 'store.png'}],
    }
    record.project['visualAssets'] = ([{
        'id': 'previous-video', 'shotId': 's1', 'valid': True, 'mediaType': 'video',
        'objectKey': 'previous.mp4', 'lastFrameObjectKey': 'tail.jpg',
    }] if cascade else [])
    if case == 'h3-strict':
        current['characterIds'] = []
    if case == 'h3-explicit':
        current['firstFrameUrl'] = 'https://assets.example.test/explicit.jpg'
    if case == 'h3-missing-tail':
        record.project['visualAssets'] = []
    if case == 'wan-single':
        current['characterIds'] = ['qing']
    if case == 'wan-existing':
        record.project['visualAssets'] = [{
            'id': 'seed', 'shotId': 's2', 'valid': True, 'mediaType': 'image',
            'objectKey': 'existing.png',
        }]
    await p._repository.save(record)
    p._asset_store = ReferenceStore()

    def forbidden(request):
        raise AssertionError('Preparation must never contact a provider')

    if case.startswith('h3-'):
        p.set_video_provider(MinimaxH3Provider(
            api_key='offline-only', prompt_mode=(
                'local-skill' if case == 'h3-local-skill' else 'context-ir'),
            transport=httpx.MockTransport(forbidden)))
    elif case.startswith('wan-'):
        text = case == 'wan-text'
        p.set_video_provider(BailianImageToVideoProvider(
            api_key='offline-only', model='wan2.2-t2v-plus' if text else 'wan2.2-i2v-flash',
            generation_type='t2v' if text else 'i2v', resolution='720P',
            transport=httpx.MockTransport(forbidden)))
    preview = await p.preview_shot_visual(pid, 's2', expected_version=version)
    return preview


@pytest.mark.parametrize('case', CASES)
async def test_preparation_contract_after_quality_review(case):
    expected = json.loads(FIXTURE.read_text(encoding='utf-8'))
    actual = await capture_preparation(case)
    baseline = expected[case]
    quality = json.loads(FIXTURE.with_name('video-preparation-quality-contract.json').read_text(
        encoding='utf-8'))
    assert actual == quality[case]
    # Preserve the original extraction baseline; only the reviewed quality fields change.
    for key in ('model', 'adapter', 'parameters', 'mode', 'calls', 'errors',
                'references', 'price', 'modelConfigRevision', 'projectVersion',
                'shotId', 'textModel', 'style', 'speech', 'actionStates'):
        assert actual.get(key) == baseline.get(key), key
    assert actual['ready'] == baseline['ready']
    assert set(baseline['warnings']).issubset(set(actual['warnings']))
