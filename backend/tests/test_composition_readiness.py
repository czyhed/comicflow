"""Composition must refuse to run before every shot has its required assets.

The delivery film is assembled from per-shot visuals and voices. Queueing a
composition while shots are still missing assets produced a silently degraded
export (text cards instead of the generated film), which hides the real gap
instead of reporting it.
"""

from typing import Any

import pytest
from comicflow.api.app import create_app
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def _confirmed_project(pipeline: Any) -> tuple[str, dict[str, Any]]:
    created = await pipeline.create_project(
        CreateProject(
            input_type="story",
            story="暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
            duration_sec=60,
            mode="automatic",
        )
    )
    project_id = created["project"]["id"]
    await pipeline.generate_story_text(project_id)
    generated = await pipeline.split_script(project_id)
    confirmed = await pipeline.confirm_script(
        project_id, expected_version=generated["project"]["version"]
    )
    return project_id, confirmed


async def test_composition_is_refused_when_no_shot_has_a_visual() -> None:
    """A confirmed script alone must not be composable."""
    pipeline = create_memory_runtime().pipeline
    project_id, confirmed = await _confirmed_project(pipeline)

    with pytest.raises(DomainError) as error:
        await pipeline.request_composition(
            project_id, expected_version=confirmed["project"]["version"]
        )

    assert error.value.code == "ASSETS_INCOMPLETE"


async def test_composition_is_refused_when_only_some_shots_have_visuals() -> None:
    """Reproduces the observed defect: one generated shot, ten-shot film exported."""
    pipeline = create_memory_runtime().pipeline
    project_id, confirmed = await _confirmed_project(pipeline)
    shots = confirmed["script"]["shots"]
    assert len(shots) > 1, "the fixture needs several shots to detect a partial film"

    visual = await pipeline.generate_shot_visual(
        project_id, str(shots[0]["id"]), expected_version=confirmed["project"]["version"]
    )
    await pipeline.adopt_video_job(project_id, visual["jobId"])

    with pytest.raises(DomainError) as error:
        await pipeline.request_composition(project_id, expected_version=visual["projectVersion"])

    assert error.value.code == "ASSETS_INCOMPLETE"


async def test_composition_is_refused_when_a_speaking_shot_has_no_voice() -> None:
    """Visuals alone are not a film: shots with lines must be voiced."""
    pipeline = create_memory_runtime().pipeline
    project_id, confirmed = await _confirmed_project(pipeline)
    version = confirmed["project"]["version"]
    for shot in confirmed["script"]["shots"]:
        result = await pipeline.generate_shot_visual(
            project_id, str(shot["id"]), expected_version=version
        )
        await pipeline.adopt_video_job(project_id, result["jobId"])
        version = result["projectVersion"]

    with pytest.raises(DomainError) as error:
        await pipeline.request_composition(project_id, expected_version=version)

    assert error.value.code == "ASSETS_INCOMPLETE"


async def test_composition_proceeds_once_every_shot_is_generated() -> None:
    """The gate must not block a genuinely complete production."""
    pipeline = create_memory_runtime().pipeline
    project_id, confirmed = await _confirmed_project(pipeline)
    version = confirmed["project"]["version"]
    for shot in confirmed["script"]["shots"]:
        visual = await pipeline.generate_shot_visual(
            project_id, str(shot["id"]), expected_version=version
        )
        await pipeline.adopt_video_job(project_id, visual["jobId"])
        audio = await pipeline.generate_shot_audio(
            project_id, str(shot["id"]), expected_version=visual["projectVersion"]
        )
        version = audio["projectVersion"]

    job = await pipeline.request_composition(project_id, expected_version=version)

    assert job["status"] == "queued"
    completed = await pipeline.run_job(job["id"])
    assert completed["status"] == "succeeded"


async def test_incomplete_composition_reports_the_missing_shots_over_http() -> None:
    """The operator must see which shots are missing what, not a silent degrade."""
    runtime = create_memory_runtime()
    app = create_app(runtime)
    project_id, confirmed = await _confirmed_project(runtime.pipeline)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/projects/{project_id}/composition",
            json={"expectedVersion": confirmed["project"]["version"]},
        )

    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "ASSETS_INCOMPLETE"
    expected_missing = [str(shot["id"]) for shot in confirmed["script"]["shots"]]
    assert body["missingVisualShotIds"] == expected_missing


async def test_reserved_credits_are_not_charged_for_a_refused_composition() -> None:
    """A refused request must not consume the composition reservation."""
    pipeline = create_memory_runtime().pipeline
    project_id, confirmed = await _confirmed_project(pipeline)
    before = await pipeline.get_snapshot(project_id)

    with pytest.raises(DomainError):
        await pipeline.request_composition(
            project_id, expected_version=confirmed["project"]["version"]
        )

    after = await pipeline.get_snapshot(project_id)
    assert after["creditLedger"] == before["creditLedger"]
    assert after["jobs"] == before["jobs"]
