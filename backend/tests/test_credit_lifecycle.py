import asyncio

from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime


async def test_composition_reserves_and_settles_credits() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里修表匠发现停摆的表能倒流一分钟",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    job = await pipeline.request_composition(project_id, expected_version=1, idempotency_key="c1")
    snapshot = await pipeline.get_snapshot(project_id)
    assert snapshot["creditLedger"][-1] == {
        "type": "reservation",
        "amount": -20,
        "jobId": job["id"],
    }
    await pipeline.run_job(job["id"])
    snapshot = await pipeline.get_snapshot(project_id)
    assert snapshot["creditLedger"][-1] == {
        "type": "settlement",
        "amount": 0,
        "consumed": 20,
        "jobId": job["id"],
    }


async def test_failed_composition_releases_reserved_credits() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里修表匠发现停摆的表能倒流一分钟",
            duration_sec=60,
            mode="guided",
        )
    )
    job = await pipeline.request_composition(created["project"]["id"], expected_version=1)

    class FailingComposer:
        async def compose(self, project: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("provider unavailable")

    pipeline._composition_provider = FailingComposer()  # type: ignore[assignment]
    await pipeline.run_job(job["id"])
    snapshot = await pipeline.get_snapshot(created["project"]["id"])
    assert snapshot["creditLedger"][-1] == {
        "type": "release",
        "amount": 20,
        "reason": "provider-failed",
        "jobId": job["id"],
    }


async def test_repeated_failed_composition_releases_reserved_credits_once() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里修表匠发现停摆的表能倒流一分钟",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    job = await pipeline.request_composition(project_id, expected_version=1)

    class FailingComposer:
        async def compose(self, project: dict[str, object]) -> dict[str, object]:
            raise RuntimeError("provider unavailable")

    pipeline._composition_provider = FailingComposer()  # type: ignore[assignment]
    await pipeline.run_job(job["id"])
    await pipeline.run_job(job["id"])
    snapshot = await pipeline.get_snapshot(project_id)
    releases = [
        entry
        for entry in snapshot["creditLedger"]
        if entry["type"] == "release" and entry["jobId"] == job["id"]
    ]
    assert len(releases) == 1


async def test_replaying_succeeded_composition_is_idempotent() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里修表匠发现停摆的表能倒流一分钟",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    job = await pipeline.request_composition(project_id, expected_version=1)
    first = await pipeline.run_job(job["id"])
    replay = await pipeline.run_job(job["id"])
    assert first["status"] == "succeeded"
    assert replay == first


async def test_concurrent_composition_delivery_claims_job_once() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里修表匠发现停摆的表能倒流一分钟",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    job = await pipeline.request_composition(project_id, expected_version=1)
    calls = 0

    class CountingComposer:
        async def compose(self, project: dict[str, object]) -> dict[str, object]:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.01)
            return {
                "files": ["video.mp4", "cover.jpg", "subtitles.srt"],
                "projectId": project["id"],
            }

    pipeline._composition_provider = CountingComposer()  # type: ignore[assignment]
    results = await asyncio.gather(pipeline.run_job(job["id"]), pipeline.run_job(job["id"]))
    assert calls == 1
    assert {result["status"] for result in results} <= {"running", "succeeded"}


async def test_cancelling_queued_composition_releases_credits_once() -> None:
    pipeline = create_memory_runtime().pipeline
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜里修表匠发现停摆的表能倒流一分钟",
            duration_sec=60,
            mode="guided",
        )
    )
    project_id = created["project"]["id"]
    job = await pipeline.request_composition(project_id, expected_version=1)
    cancelled = await pipeline.cancel_job(job["id"])
    assert cancelled["status"] == "cancelled"
    snapshot = await pipeline.get_snapshot(project_id)
    assert snapshot["creditLedger"][-1]["type"] == "release"
    assert (await pipeline.cancel_job(job["id"]))["status"] == "cancelled"
    assert len([entry for entry in snapshot["creditLedger"] if entry["type"] == "release"]) == 1
