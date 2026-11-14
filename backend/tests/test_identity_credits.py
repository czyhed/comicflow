from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def test_anonymous_project_can_be_claimed_idempotently_and_credits_are_visible() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "雨夜里，修表匠发现停摆的表能倒流一分钟",
                "durationSec": 60,
                "mode": "guided",
            },
        )
        project_id = created.json()["project"]["id"]
        claim = await client.post(
            f"/api/projects/{project_id}/claim",
            headers={"X-User-Id": "user-42"},
        )
        assert claim.status_code == 200
        assert claim.json()["project"]["ownerUserId"] == "user-42"
        repeat = await client.post(
            f"/api/projects/{project_id}/claim",
            headers={"X-User-Id": "user-42"},
        )
        assert repeat.status_code == 200
        credits = await client.get(
            f"/api/projects/{project_id}/credits", headers={"X-User-Id": "user-42"}
        )
        assert credits.status_code == 200
        assert credits.json()["available"] == 100
        forbidden = await client.get(f"/api/projects/{project_id}", headers={"X-User-Id": "other"})
        assert forbidden.status_code == 403
        forbidden_mutation = await client.post(
            f"/api/projects/{project_id}/script", headers={"X-User-Id": "other"}, json={}
        )
        assert forbidden_mutation.status_code == 403
