from comicflow.api.app import create_app
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def _create_scripted_project(client: AsyncClient) -> tuple[str, dict[str, object]]:
    created = await client.post(
        "/api/projects",
        json={
            "inputType": "story",
            "story": "暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
            "durationSec": 60,
            "mode": "guided",
        },
    )
    project_id = created.json()["project"]["id"]
    generated = await client.post(f"/api/projects/{project_id}/script", json={})
    return project_id, generated.json()


async def test_shot_character_assignment_is_available_over_http() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, generated = await _create_scripted_project(client)
        shot_id = generated["script"]["shots"][0]["id"]
        version = generated["project"]["version"]

        templates = (await client.get("/api/characters")).json()
        response = await client.put(
            f"/api/projects/{project_id}/script/shots/{shot_id}/characters",
            json={"characterIds": [templates[0]["id"]], "expectedVersion": version},
        )

        assert response.status_code == 200
        assert response.json()["characterIds"] == [templates[0]["id"]]


async def test_sse_emits_event_id_and_accepts_last_event_id() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, _ = await _create_scripted_project(client)
        first = await client.get(f"/api/projects/{project_id}/events")
        resumed = await client.get(
            f"/api/projects/{project_id}/events", headers={"Last-Event-ID": "1"}
        )

        assert first.status_code == 200
        assert "id: 1" in first.text
        assert resumed.status_code == 200
        assert "id: 2" in resumed.text


async def test_sse_numeric_progress_reconnect_does_not_replay_generation_events() -> None:
    runtime = create_memory_runtime()
    app = create_app(runtime)
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story", story="一个足够长的自动故事输入", duration_sec=30, mode="automatic"
        )
    )
    project_id = created["project"]["id"]
    await runtime.pipeline.generate_story_text(project_id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resumed = await client.get(
            f"/api/projects/{project_id}/events", headers={"Last-Event-ID": "1"}
        )

    assert "event: generation" not in resumed.text


async def test_script_update_with_stale_version_returns_stable_conflict() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, generated = await _create_scripted_project(client)
        response = await client.patch(
            f"/api/projects/{project_id}/script",
            json={"expectedVersion": generated["project"]["version"] - 1, "script": {}},
        )

        assert response.status_code == 409
        assert response.json() == {"error": "VERSION_CONFLICT"}


async def test_export_manifest_has_a_stable_read_contract() -> None:
    runtime = create_memory_runtime()
    app = create_app(runtime)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, generated = await _create_scripted_project(client)
        not_ready = await client.get(f"/api/projects/{project_id}/export")
        assert not_ready.status_code == 401
        assert not_ready.json() == {"error": "AUTH_REQUIRED"}

        shot_id = generated["script"]["shots"][2]["id"]
        version = generated["project"]["version"]
        visual = await client.post(
            f"/api/projects/{project_id}/shots/{shot_id}/visual",
            json={"expectedVersion": version},
        )
        assert visual.status_code == 200, visual.text
        assert visual.json()["awaitingAdoption"] is True
        adopted = await client.post(
            f"/api/projects/{project_id}/video-jobs/{visual.json()['jobId']}/adopt",
        )
        assert adopted.status_code == 200, adopted.text
        audio = await client.post(
            f"/api/projects/{project_id}/shots/{shot_id}/audio",
            json={"expectedVersion": visual.json()["projectVersion"]},
        )
        version = audio.json()["projectVersion"]

        # Exporting requires a complete film, so generate the remaining shots.
        for shot in generated["script"]["shots"]:
            if shot["id"] == shot_id:
                continue
            remaining_visual = await client.post(
                f"/api/projects/{project_id}/shots/{shot['id']}/visual",
                json={"expectedVersion": version},
            )
            assert remaining_visual.status_code == 200, remaining_visual.text
            assert remaining_visual.json()["awaitingAdoption"] is True
            candidate_job_id = remaining_visual.json()["jobId"]
            adopted = await client.post(
                f"/api/projects/{project_id}/video-jobs/{candidate_job_id}/adopt",
            )
            assert adopted.status_code == 200, adopted.text
            remaining_audio = await client.post(
                f"/api/projects/{project_id}/shots/{shot['id']}/audio",
                json={"expectedVersion": remaining_visual.json()["projectVersion"]},
            )
            version = remaining_audio.json()["projectVersion"]

        composition = await client.post(
            f"/api/projects/{project_id}/composition",
            json={"expectedVersion": version},
        )
        await runtime.pipeline.run_job(composition.json()["id"])

        await client.post(f"/api/projects/{project_id}/claim", headers={"X-User-Id": "owner"})
        not_ready_for_guest = await client.get(f"/api/projects/{project_id}/export")
        assert not_ready_for_guest.status_code == 401
        ready = await client.get(
            f"/api/projects/{project_id}/export", headers={"X-User-Id": "owner"}
        )
        assert ready.status_code == 200
        assert ready.json()["files"] == ["video.mp4", "cover.jpg", "subtitles.srt"]


async def test_scoped_regeneration_route_returns_scope_and_timeline() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        project_id, generated = await _create_scripted_project(client)
        shot_id = generated["script"]["shots"][2]["id"]
        version = generated["project"]["version"]
        visual = await client.post(
            f"/api/projects/{project_id}/shots/{shot_id}/visual", json={"expectedVersion": version}
        )
        assert visual.status_code == 200, visual.text
        assert visual.json()["awaitingAdoption"] is True
        adopted = await client.post(
            f"/api/projects/{project_id}/video-jobs/{visual.json()['jobId']}/adopt",
        )
        assert adopted.status_code == 200, adopted.text
        response = await client.post(
            f"/api/projects/{project_id}/shots/{shot_id}/regenerate",
            json={"scope": "audio", "expectedVersion": visual.json()["projectVersion"]},
        )
        assert response.status_code == 200
        assert response.json()["scope"] == "audio"
        assert response.json()["timeline"]["visualAssetId"] == visual.json()["asset"]["id"]
