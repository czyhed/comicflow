"""Offline regressions for the editor's actual preview/commit route."""

from copy import deepcopy

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.bailian_text import BailianTextProvider
from comicflow.providers.mock import MockTextProvider


async def script_fixture():
    body = await MockTextProvider().split_script("雨夜，李明和王芳在车站相遇。", "fixture", 30)
    script = body["content"]
    for shot in script["shots"]:
        shot["characters"] = []
    script["shots"][0]["characters"] = ["李明", "王芳"]
    script["shots"][1]["characters"] = ["李明"]
    return script


async def test_preview_commit_creates_reusable_project_cards_without_generation():
    candidate = await script_fixture()

    class Provider(MockTextProvider):
        async def split_script(self, *args, **kwargs):
            return deepcopy(candidate)

    runtime = create_memory_runtime()
    runtime.pipeline.set_text_provider(Provider())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/projects",
                json={
                    "inputType": "story",
                    "story": "雨夜，李明和王芳在车站相遇。",
                    "durationSec": 30,
                    "mode": "import_story",
                },
            )
        ).json()
        path = "/api/projects/" + created["project"]["id"]
        before = (await client.get(path)).json()
        preview = (await client.post(path + "/script/preview")).json()
        assert (await client.get(path)).json() == before
        assert len(await runtime.pipeline._character_repository.list()) == 1  # system template only
        assert len(preview["script"]["shots"][0]["characterIds"]) == 2
        payload = {k: preview[k] for k in ("script", "expectedVersion")}
        committed = await client.put(path + "/script/preview", json=payload)
        assert committed.status_code == 200, committed.text
        assert committed.json()["script"] == preview["script"]
        refused = await client.post(
            path + "/script/confirm",
            json={
                "expectedVersion": committed.json()["project"]["version"],
            },
        )
        assert refused.status_code == 400
        assert refused.json()["error"] == "CHARACTER_FIELDS_REQUIRED"
        cards = (await client.get(path + "/characters")).json()
        assert {c["name"] for c in cards} == {"李明", "王芳"}
        assert set(preview["script"]["shots"][0]["characterIds"]) == {c["id"] for c in cards}
        second = (await client.post(path + "/script/preview")).json()
        assert (
            second["script"]["shots"][0]["characterIds"]
            == preview["script"]["shots"][0]["characterIds"]
        )
        assert (await client.put(path + "/script/preview", json=payload)).status_code == 409
        assert (await client.get(path + "/characters")).json() == cards
        card = cards[0]
        edited = await client.patch(
            path + "/characters/" + card["id"],
            json={
                **card,
                "appearance": "短发，戴眼镜",
                "clothing": "蓝色外套",
                "personality": "沉稳",
                "voice": {"language": "zh-CN"},
            },
        )
        assert edited.status_code == 200, edited.text
        assert (await client.get(path + "/characters")).json()[0]["appearance"] == "短发，戴眼镜"
        unbound = await client.put(
            path + "/script/shots/" + candidate["shots"][0]["id"] + "/characters",
            json={
                "characterIds": [],
                "expectedVersion": committed.json()["project"]["version"],
            },
        )
        assert unbound.status_code == 200
        synced = await client.post(
            path + "/characters/sync",
            json={
                "expectedVersion": unbound.json()["projectVersion"],
            },
        )
        assert synced.status_code == 200
        assert synced.json()["script"]["shots"][0]["characterIds"] == []
        assert synced.json()["project"]["version"] == unbound.json()["projectVersion"]


async def test_sync_recovers_old_names_and_checks_project_access():
    runtime = create_memory_runtime()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        created = (
            await client.post(
                "/api/projects",
                json={
                    "inputType": "story",
                    "story": "雨夜，李明和王芳在车站相遇。",
                    "durationSec": 30,
                    "mode": "import_story",
                },
            )
        ).json()
        pid = created["project"]["id"]
        path = "/api/projects/" + pid
        await client.patch(
            path + "/script",
            json={
                "script": await script_fixture(),
                "expectedVersion": created["project"]["version"],
            },
        )
        version = (await client.get(path)).json()["project"]["version"]
        stale = await client.post(path + "/characters/sync", json={"expectedVersion": version - 1})
        assert stale.status_code == 409
        assert (await client.get(path + "/characters")).json() == []
        synced = await client.post(path + "/characters/sync", json={"expectedVersion": version})
        assert synced.status_code == 200
        assert len((await client.get(path + "/characters")).json()) == 2
        await runtime.pipeline.claim_project(pid, user_id="owner")
        for method, suffix, payload in [
            ("GET", "/characters", None),
            ("POST", "/characters/sync", {"expectedVersion": version + 1}),
            ("POST", "/characters", {"name": "入侵者"}),
        ]:
            denied = await client.request(method, path + suffix, json=payload)
            assert denied.status_code == 403


async def test_invalid_character_reference_cannot_create_partial_cards():
    from comicflow.domain.errors import DomainError
    from comicflow.domain.models import CreateProject

    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(
        CreateProject(
            input_type="story",
            story="雨夜，李明和王芳在车站相遇。",
            duration_sec=30,
            mode="import_story",
        )
    )
    script = await script_fixture()
    script["shots"][-1]["characterIds"] = ["nonexistent"]
    with pytest.raises(DomainError):
        await runtime.pipeline.commit_script_preview(
            created["project"]["id"],
            script,
            expected_version=created["project"]["version"],
        )
    assert len(await runtime.pipeline._character_repository.list()) == 1


async def test_adapter_keeps_recognized_names_in_legacy_shape():
    script = await script_fixture()
    result = BailianTextProvider._normalize_script(script, target_duration_sec=30)
    assert result["shots"][0]["characters"] == ["李明", "王芳"]


@pytest.mark.parametrize(
    "description",
    [
        "rain-streaked window reflects blurred city lights",
        "车窗\ufffd倒影",
        r"\u8f66\u7a97",
    ],
)
async def test_generated_script_rejects_english_or_corrupt_descriptions(description):
    script = await script_fixture()
    script["shots"][0]["visualDescription"] = description
    body = {"kind": "script", "version": 1, "content": script}
    with pytest.raises(RuntimeError):
        BailianTextProvider._normalize_script(body, target_duration_sec=30)
