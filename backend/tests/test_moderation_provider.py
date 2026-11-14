import httpx
import pytest
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.moderation import ModerationHttpProvider


@pytest.mark.asyncio
async def test_moderation_provider_returns_approve_outcome() -> None:
    provider = ModerationHttpProvider(
        api_key="secret",
        base_url="https://moderation.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"result": "approve"})),
    )
    assert await provider.moderate("safe story") == {
        "status": "approved",
        "provider": "real",
        "modelVersion": "moderation-v1",
    }


@pytest.mark.asyncio
async def test_moderation_provider_maps_review_and_timeout() -> None:
    review = ModerationHttpProvider(
        api_key="secret",
        base_url="https://moderation.test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"result": "review"})),
    )
    assert (await review.moderate("uncertain"))["status"] == "review"

    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    timed_out = ModerationHttpProvider(
        api_key="secret", base_url="https://moderation.test", transport=httpx.MockTransport(timeout)
    )
    assert (await timed_out.moderate("slow"))["status"] == "review"
    assert (await timed_out.moderate("slow"))["reasonCode"] == "PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_pipeline_uses_moderation_provider_before_reserving_generation_credit() -> None:
    runtime = create_memory_runtime()

    class BlockingProvider:
        async def moderate(self, text: str) -> dict[str, object]:
            assert text
            return {"status": "blocked", "reasonCode": "POLICY_BLOCK", "provider": "test"}

    runtime.pipeline._moderation_provider = BlockingProvider()  # type: ignore[assignment]
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="safe story for moderation", duration_sec=60, mode="guided"
        )
    )

    with pytest.raises(Exception, match="MODERATION_BLOCKED"):
        await runtime.pipeline.generate_script(created["project"]["id"])
    snapshot = await runtime.pipeline.get_snapshot(created["project"]["id"])
    assert snapshot["creditLedger"] == [{"type": "grant", "amount": 100}]


@pytest.mark.asyncio
async def test_pipeline_puts_review_content_on_hold_without_reserving_credit() -> None:
    runtime = create_memory_runtime()

    class ReviewProvider:
        async def moderate(self, text: str) -> dict[str, object]:
            return {"status": "review", "reasonCode": "PROVIDER_TIMEOUT", "provider": "test"}

    runtime.pipeline._moderation_provider = ReviewProvider()  # type: ignore[assignment]
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="safe story requires manual review",
            duration_sec=60,
            mode="guided",
        )
    )
    with pytest.raises(Exception, match="MODERATION_REVIEW_REQUIRED"):
        await runtime.pipeline.generate_script(created["project"]["id"])
    snapshot = await runtime.pipeline.get_snapshot(created["project"]["id"])
    assert snapshot["project"]["stage"] == "moderation-review"
    assert snapshot["creditLedger"] == [{"type": "grant", "amount": 100}]
