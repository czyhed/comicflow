import pytest
from comicflow.api.app import create_app, create_configured_runtime
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_memory_runtime_env_supports_real_http_production_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMICFLOW_RUNTIME", "memory")
    runtime = create_configured_runtime()
    app = create_app(runtime)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
                "durationSec": 60,
                "mode": "guided",
            },
        )
        assert created.status_code == 201
        project_id = created.json()["project"]["id"]

        generated = await client.post(f"/api/projects/{project_id}/script")
        assert generated.status_code == 200
        generated_body = generated.json()
        edited_script = generated_body["script"]
        edited_script["title"] = "编辑后的雨夜末班车"
        updated = await client.patch(
            f"/api/projects/{project_id}/script",
            json={"script": edited_script, "expectedVersion": generated_body["project"]["version"]},
        )
        assert updated.status_code == 200
        confirmed = await client.post(
            f"/api/projects/{project_id}/script/confirm",
            json={"expectedVersion": updated.json()["project"]["version"]},
        )
        assert confirmed.status_code == 200
        shots = confirmed.json()["script"]["shots"]
        shot = shots[2]
        visual = await client.post(
            f"/api/projects/{project_id}/shots/{shot['id']}/visual",
            json={"expectedVersion": confirmed.json()["project"]["version"]},
        )
        assert visual.status_code == 200, visual.text
        assert visual.json()["awaitingAdoption"] is True
        adopted = await client.post(
            f"/api/projects/{project_id}/video-jobs/{visual.json()['jobId']}/adopt",
        )
        assert adopted.status_code == 200, adopted.text
        assert visual.status_code == 200
        audio = await client.post(
            f"/api/projects/{project_id}/shots/{shot['id']}/audio",
            json={"expectedVersion": visual.json()["projectVersion"]},
        )
        assert audio.status_code == 200
        version = audio.json()["projectVersion"]

        # Composition is gated on a fully generated film, so finish every shot.
        for remaining in shots:
            if remaining["id"] == shot["id"]:
                continue
            remaining_visual = await client.post(
                f"/api/projects/{project_id}/shots/{remaining['id']}/visual",
                json={"expectedVersion": version},
            )
            assert remaining_visual.status_code == 200, remaining_visual.text
            assert remaining_visual.json()["awaitingAdoption"] is True
            candidate_job_id = remaining_visual.json()["jobId"]
            adopted = await client.post(
                f"/api/projects/{project_id}/video-jobs/{candidate_job_id}/adopt",
            )
            assert adopted.status_code == 200, adopted.text
            assert remaining_visual.status_code == 200
            remaining_audio = await client.post(
                f"/api/projects/{project_id}/shots/{remaining['id']}/audio",
                json={"expectedVersion": remaining_visual.json()["projectVersion"]},
            )
            assert remaining_audio.status_code == 200
            version = remaining_audio.json()["projectVersion"]

        composition = await client.post(
            f"/api/projects/{project_id}/composition",
            json={"expectedVersion": version, "idempotencyKey": "http-v1"},
        )
        assert composition.status_code == 202

        completed = await runtime.pipeline.run_job(composition.json()["id"])
        assert completed["status"] == "succeeded"

        claimed = await client.post(
            f"/api/projects/{project_id}/claim", headers={"X-User-Id": "local-user"}
        )
        assert claimed.status_code == 200
        export = await client.get(
            f"/api/projects/{project_id}/export", headers={"X-User-Id": "local-user"}
        )
        assert export.status_code == 200
        assert export.json()["files"] == ["video.mp4", "cover.jpg", "subtitles.srt"]
        credits = await client.get(
            f"/api/projects/{project_id}/credits", headers={"X-User-Id": "local-user"}
        )
        assert credits.status_code == 200
        assert credits.json()["available"] == 76

        events = await client.get(
            f"/api/projects/{project_id}/events",
            headers={"X-User-Id": "local-user", "Last-Event-ID": "3"},
        )
        assert events.status_code == 200
        assert "id: 4" in events.text
        assert "\nevent: progress\ndata: " in events.text

        forbidden_events = await client.get(
            f"/api/projects/{project_id}/events", headers={"X-User-Id": "other-user"}
        )
        assert forbidden_events.status_code == 403
        assert forbidden_events.json() == {"error": "PROJECT_ACCESS_DENIED"}
