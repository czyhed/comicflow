from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from comicflow.domain.models import JsonObject


class OutboxRepository(Protocol):
    async def pending_outbox(self, *, limit: int = 100) -> list[JsonObject]: ...

    async def mark_outbox_published(self, event_id: str) -> bool: ...


Publish = Callable[[str, JsonObject], Awaitable[None]]


class OutboxDispatcher:
    def __init__(self, repository: OutboxRepository, publish: Publish) -> None:
        self._repository = repository
        self._publish = publish

    async def dispatch_once(self, *, limit: int = 100) -> int:
        published = 0
        for event in await self._repository.pending_outbox(limit=limit):
            claim = getattr(self._repository, "claim_outbox", None)
            if claim is not None and not await claim(str(event["id"])):
                continue
            try:
                await self._publish(str(event["topic"]), event["payload"])
            except Exception:
                release = getattr(self._repository, "release_outbox_claim", None)
                if release is not None:
                    await release(str(event["id"]))
                raise
            if await self._repository.mark_outbox_published(str(event["id"])):
                published += 1
        return published
