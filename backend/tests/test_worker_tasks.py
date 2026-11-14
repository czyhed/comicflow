import pytest
from comicflow.worker.celery_app import create_celery_app, publish_to_celery


def test_celery_app_uses_late_ack_and_single_prefetch() -> None:
    app = create_celery_app("redis://test:6379/0")
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1


@pytest.mark.asyncio
async def test_generation_event_publishes_project_id_only(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def send_task(name: str, *, kwargs: dict[str, object]) -> None:
        captured.update({"name": name, "kwargs": kwargs})

    monkeypatch.setattr("comicflow.worker.celery_app.celery_app.send_task", send_task)
    await publish_to_celery(
        "production.generation.advance", {"projectId": "prj_1", "sessionId": "gen_1"}
    )
    assert captured == {
        "name": "comicflow.worker.advance_generation_session",
        "kwargs": {"project_id": "prj_1"},
    }
