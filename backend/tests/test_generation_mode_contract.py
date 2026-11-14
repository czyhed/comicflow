import asyncio

import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.message_contract import normalize_generation_message


def test_generation_message_requires_expected_mode_and_task() -> None:
    message = {
        "kind": "story_text",
        "version": 1,
        "mode": "automatic",
        "task": "story_expansion",
        "content": {"text": "一个足够长的故事文本" * 50},
    }

    normalized = normalize_generation_message(
        message,
        expected_kind="story_text",
        expected_mode="automatic",
        expected_task="story_expansion",
    )

    assert normalized["mode"] == "automatic"
    assert normalized["task"] == "story_expansion"


def test_generation_message_rejects_a_message_from_another_mode() -> None:
    with pytest.raises(RuntimeError, match="GENERATION_MODE_MISMATCH"):
        normalize_generation_message(
            {
                "kind": "story_text",
                "version": 1,
                "mode": "guided",
                "task": "script_outline",
                "content": {},
            },
            expected_kind="story_text",
            expected_mode="automatic",
            expected_task="story_expansion",
        )


@pytest.mark.asyncio
async def test_automatic_project_cannot_use_guided_script_endpoint() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动故事输入", duration_sec=60, mode="automatic"
        )
    )

    with pytest.raises(Exception, match="WORKFLOW_MODE_MISMATCH"):
        await runtime.pipeline.generate_script(created["project"]["id"])


@pytest.mark.asyncio
async def test_guided_project_cannot_use_automatic_story_endpoint() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的逐步故事输入", duration_sec=60, mode="guided"
        )
    )

    with pytest.raises(Exception, match="WORKFLOW_MODE_MISMATCH"):
        await runtime.pipeline.generate_story_text(created["project"]["id"])


@pytest.mark.asyncio
async def test_completed_generation_is_returned_without_calling_provider_again() -> None:
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动故事输入", duration_sec=60, mode="automatic"
        )
    )
    first = await runtime.pipeline.generate_story_text(created["project"]["id"])
    second = await runtime.pipeline.generate_story_text(created["project"]["id"])

    assert second == first


@pytest.mark.asyncio
async def test_duplicate_generation_request_is_rejected_while_provider_is_running() -> None:
    class SlowProvider:
        async def generate_story_text(
            self, _story: str, _project_id: str, target_duration_sec: int = 60
        ) -> str:
            del target_duration_sec
            await asyncio.sleep(0.05)
            return "一个足够长的故事文本" * 80

    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(SlowProvider())
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动故事输入", duration_sec=60, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    first = asyncio.create_task(runtime.pipeline.generate_story_text(project_id))
    await asyncio.sleep(0)
    with pytest.raises(Exception, match="GENERATION_IN_PROGRESS"):
        await runtime.pipeline.generate_story_text(project_id)
    await first
