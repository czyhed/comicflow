from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from comicflow.domain.models import JsonObject
from comicflow.infrastructure.redis_namespace import resolve_redis_namespace


class GenerationStateStore(Protocol):
    async def get_state(self, project_id: str) -> JsonObject | None: ...

    async def set_state(self, project_id: str, state: Mapping[str, object]) -> None: ...

    async def append_event(self, project_id: str, data: Mapping[str, object]) -> str: ...

    async def read_events(
        self, project_id: str, *, last_event_id: str = "0"
    ) -> list[JsonObject]: ...


class InMemoryGenerationStateStore:
    def __init__(self) -> None:
        self._states: dict[str, JsonObject] = {}
        self._events: dict[str, list[JsonObject]] = {}

    async def get_state(self, project_id: str) -> JsonObject | None:
        state = self._states.get(project_id)
        return json.loads(json.dumps(state)) if state is not None else None

    async def set_state(self, project_id: str, state: Mapping[str, object]) -> None:
        self._states[project_id] = json.loads(json.dumps(dict(state)))

    async def append_event(self, project_id: str, data: Mapping[str, object]) -> str:
        events = self._events.setdefault(project_id, [])
        event_id = str(len(events) + 1)
        events.append({"id": event_id, "data": json.loads(json.dumps(dict(data)))})
        return event_id

    async def read_events(self, project_id: str, *, last_event_id: str = "0") -> list[JsonObject]:
        try:
            cursor = int(last_event_id)
        except ValueError:
            cursor = 0
        return [
            json.loads(json.dumps(event))
            for event in self._events.get(project_id, [])
            if int(str(event["id"])) > cursor
        ]


class RedisGenerationStateStore:
    def __init__(
        self, redis_url: str, *, state_ttl_seconds: int = 86_400,
        namespace: str | None = None,
    ) -> None:
        from redis.asyncio import Redis

        self._namespace = resolve_redis_namespace(namespace) or "comicflow"
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._ttl = state_ttl_seconds

    def _state_key(self, project_id: str) -> str:
        return f"{self._namespace}:generation:{project_id}"

    def _event_key(self, project_id: str) -> str:
        return f"{self._namespace}:generation:events:{project_id}"

    async def get_state(self, project_id: str) -> JsonObject | None:
        value = await self._redis.get(self._state_key(project_id))
        if not isinstance(value, str):
            return None
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None

    async def set_state(self, project_id: str, state: Mapping[str, object]) -> None:
        await self._redis.set(
            self._state_key(project_id), json.dumps(dict(state), ensure_ascii=False), ex=self._ttl
        )

    async def append_event(self, project_id: str, data: Mapping[str, object]) -> str:
        event_id = await self._redis.xadd(
            self._event_key(project_id), {"data": json.dumps(dict(data), ensure_ascii=False)},
            maxlen=500,
        )
        await self._redis.expire(self._event_key(project_id), self._ttl)
        return str(event_id)

    async def read_events(self, project_id: str, *, last_event_id: str = "0") -> list[JsonObject]:
        cursor = last_event_id if last_event_id == "0" or "-" in last_event_id else "0"
        rows = await self._redis.xrange(self._event_key(project_id), min=f"({cursor}")
        events: list[JsonObject] = []
        for event_id, fields in rows:
            raw = fields.get("data") if isinstance(fields, dict) else None
            try:
                data = json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                data = {}
            if isinstance(data, dict):
                events.append({"id": str(event_id), "data": data})
        return events
