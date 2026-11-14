from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def test_character_api_lists_templates_and_creates_personal_card() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        templates = await client.get("/api/characters")
        assert templates.status_code == 200
        assert templates.json()[0]["source"] == "system"

        created = await client.post(
            "/api/characters",
            json={
                "name": "林默",
                "appearance": "短发",
                "clothing": "风衣",
                "personality": "冷静",
                "voice": {"provider": "mock", "voiceId": "calm"},
            },
        )
        assert created.status_code == 201
        assert created.json()["ownerType"] == "user"
        character_id = created.json()["id"]
        updated = await client.patch(
            f"/api/characters/{character_id}",
            json={
                "name": "林默（修订）",
                "appearance": "短发",
                "clothing": "风衣",
                "personality": "冷静",
                "voice": {"provider": "mock", "voiceId": "calm"},
            },
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "林默（修订）"
        deleted = await client.delete(f"/api/characters/{character_id}")
        assert deleted.status_code == 204


async def test_project_events_emits_an_sse_snapshot() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "idea",
                "story": "雨夜里，修表匠发现停摆的表能倒流一分钟",
                "durationSec": 60,
                "mode": "guided",
            },
        )
        project_id = created.json()["project"]["id"]
        events = await client.get(f"/api/projects/{project_id}/events")
        assert events.status_code == 200
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "event: progress" in events.text
        assert events.text.count("event: progress") == 1


async def test_script_preview_returns_normalized_summary_without_persisting() -> None:
    runtime = create_memory_runtime()
    app = create_app(runtime)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "一个足够长的故事输入",
                "durationSec": 60,
                "mode": "automatic",
            },
        )
        project_id = created.json()["project"]["id"]
        await runtime.pipeline.generate_story_text(project_id)
        before = await runtime.pipeline.get_snapshot(project_id)

        preview = await client.post(f"/api/projects/{project_id}/script/preview")

        assert preview.status_code == 200
        body = preview.json()
        assert body["summary"]["scenes"] >= 1
        assert body["summary"]["shots"] >= 1
        assert "dialogue" in body["summary"]
        after = await runtime.pipeline.get_snapshot(project_id)
        assert after["project"]["version"] == before["project"]["version"]
        assert after["script"] is None
