from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def test_guest_can_create_project_generate_script_and_read_snapshot() -> None:
    app = create_app(create_memory_runtime())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created_response = await client.post(
            "/api/projects",
            json={
                "inputType": "idea",
                "story": "雨夜里，修表匠发现停摆的表能倒流一分钟",
                "durationSec": 60,
                "mode": "guided",
            },
        )

        assert created_response.status_code == 201
        created = created_response.json()
        assert created["project"]["stage"] == "story"
        assert created["guestSession"]["projectId"] == created["project"]["id"]
        assert created["estimate"] == {"shots": 9, "creditMin": 20, "creditMax": 28}

        project_id = created["project"]["id"]
        generated_response = await client.post(
            f"/api/projects/{project_id}/script",
            headers={"Idempotency-Key": "script-v1"},
            json={},
        )

        assert generated_response.status_code == 200
        generated = generated_response.json()
        assert generated["project"]["stage"] == "awaiting-confirmation"
        assert len(generated["script"]["shots"]) == 9

        snapshot_response = await client.get(f"/api/projects/{project_id}")

        assert snapshot_response.status_code == 200
        snapshot = snapshot_response.json()
        assert snapshot["project"]["id"] == project_id
        assert snapshot["creditLedger"] == [
            {"type": "grant", "amount": 100},
            {"type": "reservation", "amount": -4},
            {"type": "settlement", "amount": 0, "consumed": 4},
        ]


async def test_api_exposes_media_generation_and_composition_queue() -> None:
    runtime = create_memory_runtime()
    app = create_app(runtime)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = (
            await client.post(
                "/api/projects",
                json={
                    "inputType": "story",
                    "story": "暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
                    "durationSec": 60,
                    "mode": "guided",
                },
            )
        ).json()
        project_id = created["project"]["id"]
        generated = (await client.post(f"/api/projects/{project_id}/script", json={})).json()
        shots = generated["script"]["shots"]
        shot_id = shots[2]["id"]
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

        # Composition needs every shot generated, so finish the remaining ones.
        for shot in shots:
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
            json={"expectedVersion": version, "idempotencyKey": "export-api-v1"},
        )

        assert visual.status_code == 200
        assert audio.status_code == 200
        assert composition.status_code == 202
        assert composition.json()["status"] == "queued"
