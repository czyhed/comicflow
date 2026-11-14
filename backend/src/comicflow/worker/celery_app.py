from __future__ import annotations

import os

from celery import Celery

from comicflow.infrastructure.redis_namespace import resolve_redis_namespace


def create_celery_app(
    redis_url: str = "redis://localhost:6379/0", *, namespace: str | None = None,
) -> Celery:
    namespace = resolve_redis_namespace(namespace)
    app = Celery(
        "comicflow",
        broker=redis_url,
        backend=redis_url,
        include=["comicflow.worker.tasks"],
    )
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        beat_schedule={
            "dispatch-production-outbox": {
                "task": "comicflow.worker.dispatch_outbox",
                "schedule": 2.0,
            }
        },
    )
    if namespace:
        queue = f"{namespace}.tasks"
        app.conf.update(
            task_default_queue=queue,
            task_default_exchange=queue,
            task_default_routing_key=queue,
            broker_transport_options={"global_keyprefix": f"{namespace}:broker:"},
            result_backend_transport_options={"global_keyprefix": f"{namespace}:result:"},
            event_exchange=f"{namespace}.events",
            control_exchange=f"{namespace}.control",
        )
    return app


celery_app = create_celery_app(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


async def publish_to_celery(topic: str, payload: dict[str, object]) -> None:
    """Publish an outbox event to a stable task name understood by the worker."""
    task_name = {
        "production.job.queued": "comicflow.worker.run_job",
        'production.video.queued': 'comicflow.worker.run_video_job',
        'production.image.queued': 'comicflow.worker.run_image_job',
        "production.generation.advance": "comicflow.worker.advance_generation_session",
    }.get(topic)
    if task_name is None:
        raise ValueError(f"unsupported outbox topic: {topic}")
    if task_name in {"comicflow.worker.run_job", 'comicflow.worker.run_video_job',
                     'comicflow.worker.run_image_job'}:
        job_id = payload.get("jobId")
        if not isinstance(job_id, str):
            raise ValueError("production.job.queued payload requires jobId")
        celery_app.send_task(task_name, kwargs={"job_id": job_id})
        return
    if task_name == "comicflow.worker.advance_generation_session":
        project_id = payload.get("projectId")
        if not isinstance(project_id, str):
            raise ValueError("production.generation.advance payload requires projectId")
        kwargs: dict[str, object] = {"project_id": project_id}
        revision = payload.get('modelConfigRevision')
        if type(revision) is int:
            kwargs['model_config_revision'] = revision
        celery_app.send_task(task_name, kwargs=kwargs)
        return
    celery_app.send_task(task_name, kwargs=payload)
