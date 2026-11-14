from copy import deepcopy

import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock import MockTextProvider
from httpx import ASGITransport, AsyncClient


class CountingProvider(MockTextProvider):
    calls = 0

    async def split_script(self, story_text, project_id, target_duration_sec=60):
        self.calls += 1
        script = await super().split_script(story_text, project_id, target_duration_sec)
        script['title'] = f'预览版本{self.calls}'
        return script


@pytest.mark.parametrize('failure', [None, 'stale', 'reference', 'context', 'dialogue'])
async def test_preview_commit_preserves_exact_candidate_or_leaves_snapshot_untouched(failure):
    runtime = create_memory_runtime()
    provider = CountingProvider()
    runtime.pipeline.set_text_provider(provider)
    async with AsyncClient(
        transport=ASGITransport(app=create_app(runtime)), base_url='http://test'
    ) as client:
        created = await client.post('/api/projects', json={
            'inputType': 'story', 'story': '暴雨夜的末班车上，姐姐突然回头。',
            'durationSec': 60, 'mode': 'import_story',
        })
        pid = created.json()['project']['id']
        path = f'/api/projects/{pid}'
        old = {'title': '保留旧剧本', 'scenes': [], 'shots': []}
        await client.patch(path + '/script', json={
            'script': old, 'expectedVersion': created.json()['project']['version'],
        })
        before = (await client.get(path)).json()
        response = await client.post(path + '/script/preview')
        assert response.status_code == 200
        preview = response.json()
        assert preview['expectedVersion'] == before['project']['version']
        assert (await client.get(path)).json() == before
        candidate = deepcopy(preview['script'])
        version = preview['expectedVersion']
        if failure == 'stale':
            await client.patch(path + '/story', json={
                'storyText': '用户在另一窗口修改了故事内容。', 'expectedVersion': version,
            })
        elif failure == 'reference':
            candidate['scenes'][0]['shotIds'][0] = 'missing'
        elif failure == 'context':
            candidate['scenes'][0]['location'] = ['not a string']
        elif failure == 'dialogue':
            candidate['shots'][0]['dialogue'] = ['not a string']
        before_commit = (await client.get(path)).json()
        result = await client.put(path + '/script/preview', json={
            'expectedVersion': version, 'script': candidate,
        })
        after = (await client.get(path)).json()
        assert provider.calls == 1
        if failure:
            assert result.status_code == (409 if failure == 'stale' else 400)
            assert after == before_commit
        else:
            assert result.status_code == 200
            assert after['script'] == preview['script']
            assert after['project']['version'] == version + 1
            assert after['project']['stage'] == 'awaiting-confirmation'
            for card in (await client.get(path + '/characters')).json():
                await client.patch(path + '/characters/' + card['id'], json={
                    **card, 'appearance': '黑色短发', 'clothing': '灰色外套',
                    'personality': '沉稳', 'voice': {'language': 'zh-CN'},
                })
            confirmed = await client.post(path + '/script/confirm', json={
                'expectedVersion': version + 1,
            })
            assert confirmed.status_code == 200
            assert (await client.get(path)).json()['script'] == preview['script']
