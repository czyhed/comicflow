from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def test_metrics_endpoint_reports_health_checks() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/health")
        metrics = await client.get("/metrics")
        assert metrics.status_code == 200
        assert metrics.json()["health_checks_total"] == 1


async def test_metrics_endpoint_exposes_stable_production_counters() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        metrics = await client.get("/metrics")
    body = metrics.json()
    assert {
        "generation_success_total",
        "generation_retry_total",
        "moderation_blocked_total",
        "export_failure_total",
        "stage_duration_ms_total",
        "unit_export_cost_credits_total",
    }.issubset(body)


async def test_metrics_count_moderation_blocks_at_api_boundary() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "这是一个包含色情内容的故事用于测试审核",
                "durationSec": 60,
                "mode": "guided",
            },
        )
        await client.post(f"/api/projects/{created.json()['project']['id']}/script")
        metrics = await client.get("/metrics")
    assert metrics.json()["moderation_blocked_total"] == 1
