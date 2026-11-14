from comicflow.domain.models import ProjectRecord
from comicflow.infrastructure.database import Base, SqlAlchemyProjectRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def test_project_state_and_outbox_event_are_committed_together() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = SqlAlchemyProjectRepository(async_sessionmaker(engine, expire_on_commit=False))
    record = ProjectRecord(
        project={"id": "prj_1", "version": 1, "stage": "story"},
        guest_session={"id": "gst_1", "projectId": "prj_1"},
        jobs=[{"id": "job_1", "type": "composition", "status": "queued"}],
    )

    await repository.save(
        record,
        outbox_event={"topic": "production.job.queued", "payload": {"jobId": "job_1"}},
    )

    restored = await repository.get("prj_1")
    pending = await repository.pending_outbox()
    assert restored is not None
    assert restored.jobs[0]["status"] == "queued"
    assert pending[0]["payload"] == {"jobId": "job_1"}

    await engine.dispose()
