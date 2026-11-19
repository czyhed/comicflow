from __future__ import annotations

import pytest

from comicflow.api.app import create_app
from comicflow.identity.request import resolve_identity
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient

GATEWAY_HEADERS = {"X-Control-User-Id": "password%3Axshipai"}
DECODED_GATEWAY_USER = "password:xshipai"
PROJECT_BODY = {
    "inputType": "story",
    "story": "雨夜里，修表匠发现停摆的表能倒流一分钟",
    "durationSec": 60,
    "mode": "guided",
}


def _client(app) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    )


async def _create_project(client: AsyncClient, headers: dict[str, str] | None = None):
    response = await client.post("/api/projects", json=PROJECT_BODY, headers=headers or {})
    assert response.status_code == 201, response.text
    return response.json()


async def test_gateway_identity_is_decoded_and_preferred_over_legacy_header() -> None:
    app = create_app(create_memory_runtime())
    async with _client(app) as client:
        created = await _create_project(
            client,
            headers={**GATEWAY_HEADERS, "X-User-Id": "attacker"},
        )

        assert created["project"]["ownerUserId"] == DECODED_GATEWAY_USER

        # The gateway identity owns the project, so the legacy header cannot claim it.
        denied = await client.post(
            f"/api/projects/{created['project']['id']}/claim",
            headers={"X-User-Id": "attacker"},
        )
        assert denied.status_code == 403
        assert denied.json() == {"error": "PROJECT_ACCESS_DENIED"}

        claimed = await client.post(
            f"/api/projects/{created['project']['id']}/claim",
            headers=GATEWAY_HEADERS,
        )
        assert claimed.status_code == 200
        assert claimed.json()["project"]["ownerUserId"] == DECODED_GATEWAY_USER


async def test_production_never_trusts_client_supplied_x_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COMICFLOW_DEV_TRUST_X_USER_ID", raising=False)
    app = create_app(create_memory_runtime())

    async with _client(app) as client:
        created = await _create_project(client)
        project_id = created["project"]["id"]
        assert created["project"]["ownerUserId"] is None

        denied = await client.post(
            f"/api/projects/{project_id}/claim",
            headers={"X-User-Id": "password:xshipai"},
        )
        assert denied.status_code == 401
        assert denied.json() == {"error": "AUTH_REQUIRED"}

        # The gateway header remains trusted because the proxy overwrites it.
        claimed = await client.post(
            f"/api/projects/{project_id}/claim",
            headers=GATEWAY_HEADERS,
        )
        assert claimed.status_code == 200
        assert claimed.json()["project"]["ownerUserId"] == DECODED_GATEWAY_USER


async def test_legacy_header_is_honoured_only_in_explicit_dev_mode_and_is_decoded() -> None:
    app = create_app(create_memory_runtime())

    async with _client(app) as client:
        created = await _create_project(client)
        claimed = await client.post(
            f"/api/projects/{created['project']['id']}/claim",
            headers={"X-User-Id": "gst_legacy%3A1"},
        )

        assert claimed.status_code == 200
        assert claimed.json()["project"]["ownerUserId"] == "gst_legacy:1"


async def test_project_is_visible_across_sessions_for_the_same_gateway_identity() -> None:
    app = create_app(create_memory_runtime())

    async with _client(app) as first_browser:
        created = await _create_project(first_browser, headers=GATEWAY_HEADERS)
        project_id = created["project"]["id"]

    # A new AsyncClient has no cookies or browser storage: only the gateway header.
    async with _client(app) as second_browser:
        listed = await second_browser.get("/api/projects", headers=GATEWAY_HEADERS)
        assert listed.status_code == 200
        assert project_id in [item["project"]["id"] for item in listed.json()]

        snapshot = await second_browser.get(
            f"/api/projects/{project_id}", headers=GATEWAY_HEADERS,
        )
        assert snapshot.status_code == 200
        assert snapshot.json()["project"]["id"] == project_id

        forbidden = await second_browser.get(
            f"/api/projects/{project_id}",
            headers={"X-Control-User-Id": "password%3Asomeone-else"},
        )
        assert forbidden.status_code == 403
        assert forbidden.json() == {"error": "PROJECT_ACCESS_DENIED"}

        anonymous = await second_browser.get(f"/api/projects/{project_id}")
        assert anonymous.status_code == 403


async def test_magic_link_claim_stores_the_gateway_identity_not_the_email_identity() -> None:
    app = create_app(create_memory_runtime())

    async with _client(app) as client:
        issued = await client.post("/api/auth/magic-link", json={"email": "creator@example.com"})
        verified = await client.post("/api/auth/verify", json={"token": issued.json()["token"]})
        assert verified.json()["userId"] == "user_creator@example.com"

        created = await _create_project(client)
        claimed = await client.post(
            f"/api/projects/{created['project']['id']}/claim",
            headers=GATEWAY_HEADERS,
        )
        assert claimed.status_code == 200
        assert claimed.json()["project"]["ownerUserId"] == DECODED_GATEWAY_USER
        assert claimed.json()["project"]["ownerUserId"] != verified.json()["userId"]


@pytest.mark.parametrize(
    ("legacy_enabled", "headers", "expected_user", "expected_source"),
    [
        ("0", {"X-Control-User-Id": "password%3Axshipai"}, "password:xshipai", "gateway"),
        (
            "1",
            {"X-Control-User-Id": "password%3Axshipai", "X-User-Id": "attacker"},
            "password:xshipai",
            "gateway",
        ),
        ("0", {"X-User-Id": "attacker"}, None, "anonymous"),
        ("1", {"X-User-Id": "gst_dev%3A1"}, "gst_dev:1", "dev-header"),
        ("1", {"X-Control-User-Id": "   "}, None, "anonymous"),
        ("1", {"X-Control-User-Id": "a" * 257}, None, "anonymous"),
    ],
)
def test_resolve_identity_contract(
    monkeypatch: pytest.MonkeyPatch,
    legacy_enabled: str,
    headers: dict[str, str],
    expected_user: str | None,
    expected_source: str,
) -> None:
    monkeypatch.setenv("COMICFLOW_DEV_TRUST_X_USER_ID", legacy_enabled)

    identity = resolve_identity(headers)

    assert identity.user_id == expected_user
    assert identity.source == expected_source
