import pytest
from comicflow.infrastructure.generation_state import InMemoryGenerationStateStore


@pytest.mark.asyncio
async def test_generation_state_store_persists_state_and_orders_stream_events() -> None:
    store = InMemoryGenerationStateStore()

    await store.set_state(
        "prj_state",
        {"mode": "automatic", "task": "story_expansion", "status": "running"},
    )
    first = await store.append_event("prj_state", {"type": "generation_delta", "delta": "第一段"})
    second = await store.append_event("prj_state", {"type": "generation_delta", "delta": "第二段"})

    assert await store.get_state("prj_state") == {
        "mode": "automatic",
        "task": "story_expansion",
        "status": "running",
    }
    events = await store.read_events("prj_state", last_event_id=first)
    assert [event["id"] for event in events] == [second]
    assert events[0]["data"]["delta"] == "第二段"

