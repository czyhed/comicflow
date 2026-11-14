"""Behavior at existing Pipeline entry points, before and after module extraction."""
import asyncio
from copy import copy

import pytest
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock import MockTextProvider


class RecordingText(MockTextProvider):
    def __init__(self, name):
        self.name = name
        self.calls = []

    async def split_script(self, story_text, project_id, target_duration_sec=60):
        self.calls.append((story_text, project_id, target_duration_sec))
        result = await super().split_script(story_text, project_id, target_duration_sec)
        result['content']['title'] = self.name
        return result


async def test_request_copy_and_runtime_switch_keep_provider_inputs_and_preview_read_only():
    runtime = create_memory_runtime()
    pipeline = runtime.pipeline
    created = await pipeline.create_project(CreateProject(
        input_type='story', story='姐姐在雨夜车站等候失踪的妹妹。',
        duration_sec=30, mode='import_story'))
    pid = created['project']['id']
    first, second, third = (RecordingText(name) for name in ('第一版', '第二版', '第三版'))
    pipeline.set_text_provider(first)
    before = await pipeline.get_snapshot(pid)
    assert (await pipeline.preview_script(pid))['script']['title'] == '第一版'
    scoped = copy(pipeline)
    scoped.set_text_provider(second)
    assert (await scoped.preview_script(pid))['script']['title'] == '第二版'
    pipeline.set_text_provider(third)
    assert (await pipeline.preview_script(pid))['script']['title'] == '第三版'
    assert first.calls == second.calls == third.calls
    assert len(first.calls) == 1 and first.calls[0][1:] == (pid, 30)
    assert await pipeline.get_snapshot(pid) == before


async def test_concurrent_request_copy_uses_existing_lock_and_reuses_finished_story():
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockingText(MockTextProvider):
        calls = 0

        async def stream_story_text(self, story, project_id, target_duration_sec=60):
            self.calls += 1
            entered.set()
            await release.wait()
            yield '雨夜的车站里，姐姐在等候迟到的妹妹。' * 30

    pipeline = create_memory_runtime().pipeline
    provider = BlockingText()
    pipeline.set_text_provider(provider)
    created = await pipeline.create_project(CreateProject(
        input_type='idea', story='姐姐在雨夜车站等候失踪的妹妹。',
        duration_sec=30, mode='automatic'))
    pid = created['project']['id']
    scoped = copy(pipeline)
    running = asyncio.create_task(pipeline.generate_story_text(pid, idempotency_key='one'))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(DomainError, match='GENERATION_IN_PROGRESS'):
            await scoped.generate_story_text(pid, idempotency_key='two')
    finally:
        release.set()
        result = await running
    repeated = await scoped.generate_story_text(pid, idempotency_key='one')
    assert repeated == result
    assert provider.calls == 1
    ledger = result['project']['creditLedger']
    assert sum(e['type'] == 'reservation' for e in ledger) == 1
    assert sum(e['type'] == 'settlement' for e in ledger) == 1
