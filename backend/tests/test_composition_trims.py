from copy import deepcopy

import pytest
from comicflow.api.app import create_app
from comicflow.domain.errors import DomainError
from httpx import ASGITransport, AsyncClient
from test_partial_composition import prepared


async def test_trim_is_frozen_on_trial_without_editing_source():
    runtime, pid = await prepared()
    pipeline = runtime.pipeline
    before = deepcopy((await pipeline._repository.get(pid)).project)
    trims = {'a': {'inSec': .2, 'outSec': 1.8}}
    job = await pipeline.request_composition(
        pid, expected_version=1, shot_ids=['a', 'b'], shot_trims=trims,
    )
    trims['a']['inSec'] = 1
    done = await pipeline.run_job(job['id'])
    assert done['status'] == 'succeeded'
    assert pipeline._composition_provider.calls[0]['compositionTrims']['a']['inSec'] == .2
    assert done['exportManifest']['shotTrims']['a']['outSec'] == 1.8
    after = (await pipeline._repository.get(pid)).project
    for key in ('script', 'visualAssets', 'exportManifest', 'stage'):
        assert after[key] == before[key]


@pytest.mark.parametrize('trims', [
    {'missing': {'inSec': 0, 'outSec': 1}},
    {'b': {'inSec': 0, 'outSec': 1}},
    {'a': {'inSec': -1, 'outSec': 1}},
    {'a': {'inSec': 1, 'outSec': 1}},
    {'a': {'inSec': 0, 'outSec': float('inf')}},
    {'a': {'inSec': True, 'outSec': 1}},
])
async def test_invalid_trims_do_not_reserve_credit(trims):
    runtime, pid = await prepared()
    before = await runtime.pipeline._repository.get(pid)
    with pytest.raises(DomainError, match='COMPOSITION_TRIM_INVALID'):
        await runtime.pipeline.request_composition(
            pid, expected_version=1, shot_ids=['a'], shot_trims=trims,
        )
    assert await runtime.pipeline._repository.get(pid) == before


async def test_http_trim_contract_validates_before_queue():
    runtime, pid = await prepared()
    async with AsyncClient(transport=ASGITransport(app=create_app(runtime)),
                           base_url='http://test') as client:
        path = f'/api/projects/{pid}/composition'
        base = {'expectedVersion': 1, 'shotIds': ['a']}
        for trim in ({'inSec': 2, 'outSec': 1}, {'inSec': True, 'outSec': 1},
                     {'inSec': '0', 'outSec': 1}):
            result = await client.post(path, json={**base, 'shotTrims': {'a': trim}})
            assert result.status_code == 422
        result = await client.post(path, json={**base, 'shotTrims': {
            'a': {'inSec': 0, 'outSec': 1},
        }})
        assert result.status_code == 202
        assert result.json()['shotTrims'] == {'a': {'inSec': 0, 'outSec': 1}}
