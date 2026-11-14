from typing import Any

import pytest
from comicflow.worker.outbox import OutboxDispatcher


class OutboxRepositoryStub:
    def __init__(self) -> None:
        self.published: list[str] = []

    async def pending_outbox(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [
            {
                "id": "evt_1",
                "topic": "production.job.queued",
                "payload": {"jobId": "job_1"},
            }
        ][:limit]

    async def mark_outbox_published(self, event_id: str) -> bool:
        self.published.append(event_id)
        return True


async def test_outbox_is_marked_only_after_broker_accepts_the_job() -> None:
    repository = OutboxRepositoryStub()
    attempts = 0

    async def publish(_topic: str, _payload: dict[str, Any]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("REDIS_UNAVAILABLE")

    dispatcher = OutboxDispatcher(repository, publish)

    with pytest.raises(RuntimeError, match="REDIS_UNAVAILABLE"):
        await dispatcher.dispatch_once()
    assert repository.published == []

    assert await dispatcher.dispatch_once() == 1
    assert repository.published == ["evt_1"]
