"""Exercise Redis naming through the adapters without any network access."""

from unittest.mock import AsyncMock

import pytest
from comicflow.infrastructure.generation_state import RedisGenerationStateStore
from comicflow.worker.celery_app import create_celery_app
from kombu.transport.redis import PrefixedStrictRedis


@pytest.fixture(autouse=True)
def isolate_network_and_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMICFLOW_REDIS_NAMESPACE", raising=False)

    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("Redis namespace tests must remain offline")

    monkeypatch.setattr("redis.connection.Connection.connect", reject_network)
    monkeypatch.setattr("redis.asyncio.connection.Connection.connect", reject_network)


def test_workers_route_to_separate_queues_and_result_keys() -> None:
    apps = [create_celery_app("redis://fixture.invalid/0", namespace=n)
            for n in ("comicflow-a", "comicflow-b")]
    try:
        queues = []
        results = []
        for app in apps:
            for task in ("run_job", "advance_generation_session", "dispatch_outbox"):
                route = app.amqp.router.route({}, f"comicflow.worker.{task}")
                queue = route["queue"]
                assert queue.name != "celery"
                assert queue.exchange.name == queue.name
                assert queue.routing_key == queue.name
            queues.append(queue.name)
            results.append(app.backend.get_key_for_task("same-task-id"))
        assert len(set(queues)) == 2
        assert len(set(results)) == 2
        assert apps[0].conf.event_exchange != apps[1].conf.event_exchange
        assert apps[0].conf.control_exchange != apps[1].conf.control_exchange
    finally:
        for app in apps:
            app.close()


@pytest.mark.parametrize("args", [
    ("LPUSH", "celery", "message"),
    ("HSET", "unacked", "delivery", "message"),
    ("ZADD", "unacked_index", 1, "delivery"),
    ("SET", "unacked_mutex", "lock"),
    ("SADD", "_kombu.binding.celery", "binding"),
    ("PUBLISH", "/0.celery.pidbox", "control"),
    ("BRPOP", "celery", "priority-queue", 1),
])
def test_kombu_prefixes_queue_ack_lock_and_pubsub_commands(args: tuple) -> None:
    app = create_celery_app("redis://fixture.invalid/0", namespace="comicflow-a")
    try:
        with app.connection_for_write() as connection:
            prefix = connection.transport_options["global_keyprefix"]
        client = PrefixedStrictRedis(global_keyprefix=prefix)
        try:
            prefixed = client._prefix_args(args)
            assert prefixed[1] == "comicflow-a:broker:" + args[1]
            if args[0] == "BRPOP":
                assert prefixed[2] == "comicflow-a:broker:priority-queue"
                assert prefixed[-1] == 1
            else:
                assert prefixed[2:] == list(args[2:])
        finally:
            client.close()
    finally:
        app.close()


async def test_generation_state_and_events_do_not_cross_environments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[str, str] = {}
    streams: dict[str, list] = {}

    async def get(key: str):
        return values.get(key)

    async def set_value(key: str, value: str, **kwargs):
        values[key] = value

    async def xadd(key: str, fields: dict, **kwargs):
        streams.setdefault(key, []).append(("1-0", fields))
        return "1-0"

    async def xrange(key: str, **kwargs):
        return streams.get(key, [])

    client = AsyncMock()
    client.get.side_effect = get
    client.set.side_effect = set_value
    client.xadd.side_effect = xadd
    client.xrange.side_effect = xrange
    monkeypatch.setattr("redis.asyncio.Redis.from_url", lambda *a, **kw: client)
    a = RedisGenerationStateStore("redis://fixture.invalid/0", namespace="comicflow-a")
    b = RedisGenerationStateStore("redis://fixture.invalid/0", namespace="comicflow-b")
    legacy = RedisGenerationStateStore("redis://fixture.invalid/0")
    await a.set_state("same-project", {"status": "running"})
    await a.append_event("same-project", {"stage": "story"})
    assert await a.get_state("same-project") == {"status": "running"}
    assert await a.read_events("same-project") == [
        {"id": "1-0", "data": {"stage": "story"}},
    ]
    for other in (b, legacy):
        assert await other.get_state("same-project") is None
        assert await other.read_events("same-project") == []
    await legacy.set_state("old-project", {"status": "ready"})
    assert "comicflow:generation:old-project" in values


def test_environment_config_reaches_both_celery_and_state_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMICFLOW_REDIS_NAMESPACE", "comicflow-server")
    app = create_celery_app("redis://fixture.invalid/0")
    store = RedisGenerationStateStore("redis://fixture.invalid/0")
    try:
        assert app.conf.task_default_queue == "comicflow-server.tasks"
        assert store._state_key("p") == "comicflow-server:generation:p"
        assert store._event_key("p") == "comicflow-server:generation:events:p"
    finally:
        app.close()


@pytest.mark.parametrize("namespace", [" ", "x:y", "a*", "a/b", "x" * 65])
def test_invalid_namespace_fails_before_connecting(namespace: str) -> None:
    for factory in (create_celery_app, RedisGenerationStateStore):
        with pytest.raises(ValueError, match="COMICFLOW_REDIS_NAMESPACE"):
            factory("redis://fixture.invalid/0", namespace=namespace)


def test_unconfigured_local_worker_keeps_existing_queue_and_result_keys() -> None:
    app = create_celery_app("redis://fixture.invalid/0")
    try:
        assert app.conf.task_default_queue == "celery"
        assert app.backend.get_key_for_task("task") == b"celery-task-meta-task"
        assert not app.conf.broker_transport_options.get("global_keyprefix")
    finally:
        app.close()
