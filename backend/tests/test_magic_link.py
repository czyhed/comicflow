import time

from comicflow.api.app import create_app
from comicflow.identity.magic_link import MagicLinkService
from comicflow.infrastructure.memory import create_memory_runtime
from httpx import ASGITransport, AsyncClient


async def test_magic_link_is_single_use_and_returns_stable_user_identity() -> None:
    app = create_app(create_memory_runtime())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        issued = await client.post("/api/auth/magic-link", json={"email": "Creator@Example.com"})
        assert issued.status_code == 200
        token = issued.json()["token"]
        verified = await client.post("/api/auth/verify", json={"token": token})
        assert verified.json() == {
            "userId": "user_creator@example.com",
            "email": "creator@example.com",
        }
        reused = await client.post("/api/auth/verify", json={"token": token})
        assert reused.status_code == 401


def test_magic_link_expires_without_revealing_original_email_or_token() -> None:
    service = MagicLinkService(ttl_seconds=1)
    issued = service.issue("creator@example.com")
    service._issued_at[issued["token"]] = time.time() - 2
    try:
        service.verify(issued["token"])
    except ValueError as error:
        assert str(error) == "EXPIRED_MAGIC_LINK"
    else:
        raise AssertionError("expired magic links must not verify")
