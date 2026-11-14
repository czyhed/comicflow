import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.mock import MockTextProvider


class StubTextProvider:
    async def generate_script(self, _story: str, _project_id: str) -> dict[str, object]:
        message = await MockTextProvider().generate_script(_story, _project_id)
        message["content"]["title"] = "真实剧本"
        return message


class FailingTextProvider:
    async def generate_script(self, _story: str, _project_id: str) -> dict[str, object]:
        raise RuntimeError("PROVIDER_TIMEOUT")


async def test_pipeline_can_replace_text_provider_at_runtime() -> None:
    runtime = create_memory_runtime()
    project = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="这是一个足够长的故事输入", duration_sec=60, mode="guided"
        )
    )
    runtime.pipeline.set_text_provider(StubTextProvider())

    result = await runtime.pipeline.generate_script(project["project"]["id"])

    assert result["script"]["title"] == "真实剧本"


async def test_provider_timeout_is_mapped_and_reserved_credit_is_released() -> None:
    runtime = create_memory_runtime()
    project = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="这是一个足够长的故事输入", duration_sec=60, mode="guided"
        )
    )
    runtime.pipeline.set_text_provider(FailingTextProvider())

    with pytest.raises(Exception, match="PROVIDER_TIMEOUT"):
        await runtime.pipeline.generate_script(project["project"]["id"])

    snapshot = await runtime.pipeline.get_snapshot(project["project"]["id"])
    assert sum(item["amount"] for item in snapshot["project"]["creditLedger"]) == 100
