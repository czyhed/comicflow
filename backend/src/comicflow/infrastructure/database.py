from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject, ProjectRecord


class Base(DeclarativeBase):
    pass


class ModelRegistryRow(Base):
    __tablename__ = "model_registry_versions"

    revision: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class VideoJobRow(Base):
    __tablename__ = 'video_generation_jobs'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    active_slot: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    revision: Mapped[int] = mapped_column(default=0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ImageJobRow(Base):
    __tablename__ = 'image_generation_jobs'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    operation_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    active_slot: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    revision: Mapped[int] = mapped_column(default=0, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


def normalize_database_url(url: str) -> str:
    """Convert common PostgreSQL URLs to the asyncpg SQLAlchemy dialect."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def create_session_factory(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(normalize_database_url(database_url), pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class ProjectStateRow(Base):
    __tablename__ = "project_states"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CharacterRow(Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OutboxRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlAlchemyProjectRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, project_id: str) -> ProjectRecord | None:
        async with self._sessions() as session:
            row = await session.get(ProjectStateRow, project_id)
            return self._to_record(row.payload) if row else None

    async def list_projects(self) -> list[ProjectRecord]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(ProjectStateRow).order_by(ProjectStateRow.updated_at.desc())
                )
            ).all()
            return [self._to_record(row.payload) for row in rows]

    async def save(
        self, record: ProjectRecord, *, outbox_event: JsonObject | None = None
    ) -> None:
        payload = {
            "project": deepcopy(record.project),
            "guestSession": deepcopy(record.guest_session),
            "jobs": deepcopy(record.jobs),
        }
        async with self._sessions.begin() as session:
            project_id = str(record.project['id'])
            row = await session.get(ProjectStateRow, project_id, with_for_update=True)
            if row is None:
                session.add(ProjectStateRow(id=project_id, payload=payload,
                                             updated_at=datetime.now(UTC)))
            else:
                # A late editor/session save must not erase a journaled paid result.
                saved_video_ids = {a['id'] for a in row.payload['project'].get('visualAssets', [])
                                   if a.get('jobId')}
                incoming_ids = {a['id'] for a in record.project.get('visualAssets', [])}
                if not saved_video_ids <= incoming_ids:
                    raise DomainError('VERSION_CONFLICT')
                changed = await session.execute(update(ProjectStateRow).where(
                    ProjectStateRow.id == project_id,
                    ProjectStateRow.updated_at == row.updated_at,
                ).values(payload=payload, updated_at=datetime.now(UTC)).returning(
                    ProjectStateRow.id))
                if changed.scalar_one_or_none() != project_id:
                    raise DomainError('VERSION_CONFLICT')
            if outbox_event:
                session.add(
                    OutboxRow(
                        id=f"evt_{uuid4().hex}",
                        topic=str(outbox_event["topic"]),
                        payload=deepcopy(outbox_event["payload"]),
                        status="pending",
                        created_at=datetime.now(UTC),
                    )
                )

    async def find_by_job(self, job_id: str) -> ProjectRecord | None:
        async with self._sessions() as session:
            rows = (await session.scalars(select(ProjectStateRow))).all()
            for row in rows:
                record = self._to_record(row.payload)
                if any(job["id"] == job_id for job in record.jobs):
                    return record
        return None

    async def claim_job(self, job_id: str) -> ProjectRecord | None:
        async with self._sessions.begin() as session:
            rows = (await session.scalars(select(ProjectStateRow).with_for_update())).all()
            for row in rows:
                record = self._to_record(row.payload)
                for job in record.jobs:
                    if job["id"] == job_id and job["status"] in {"queued", "failed"}:
                        job["status"] = "running"
                        job["progress"] = 1
                        row.payload = {
                            "project": deepcopy(record.project),
                            "guestSession": deepcopy(record.guest_session),
                            "jobs": deepcopy(record.jobs),
                        }
                        row.updated_at = datetime.now(UTC)
                        return record
        return None

    async def pending_outbox(self, *, limit: int = 100) -> list[JsonObject]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(OutboxRow)
                    .where(OutboxRow.status == "pending")
                    .order_by(OutboxRow.created_at)
                    .limit(limit)
                )
            ).all()
            return [
                {"id": row.id, "topic": row.topic, "payload": deepcopy(row.payload)}
                for row in rows
            ]

    async def mark_outbox_published(self, event_id: str) -> bool:
        async with self._sessions.begin() as session:
            row = await session.get(OutboxRow, event_id)
            if row is None or row.status not in {"pending", "processing"}:
                return False
            row.status = "published"
            row.published_at = datetime.now(UTC)
            return True

    async def claim_outbox(self, event_id: str) -> bool:
        async with self._sessions.begin() as session:
            result = await session.execute(
                update(OutboxRow)
                .where(OutboxRow.id == event_id, OutboxRow.status == "pending")
                .values(status="processing")
            )
            return bool(getattr(result, "rowcount", 0) == 1)

    async def release_outbox_claim(self, event_id: str) -> None:
        async with self._sessions.begin() as session:
            await session.execute(
                update(OutboxRow)
                .where(OutboxRow.id == event_id, OutboxRow.status == "processing")
                .values(status="pending")
            )

    @staticmethod
    def _to_record(payload: dict[str, Any]) -> ProjectRecord:
        return ProjectRecord(
            project=deepcopy(payload["project"]),
            guest_session=deepcopy(payload["guestSession"]),
            jobs=deepcopy(payload.get("jobs", [])),
        )


class SqlAlchemyCharacterRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, character_id: str) -> JsonObject | None:
        async with self._sessions() as session:
            row = await session.get(CharacterRow, character_id)
            return deepcopy(row.payload) if row else None

    async def list(self) -> list[JsonObject]:
        async with self._sessions() as session:
            rows = (await session.scalars(select(CharacterRow))).all()
            return [deepcopy(row.payload) for row in rows]

    async def save(self, character: JsonObject, *, expected: JsonObject | None = None) -> None:
        async with self._sessions.begin() as session:
            if expected is not None:
                row = await session.get(CharacterRow, str(character['id']), with_for_update=True)
                if row is None or row.payload != expected:
                    raise DomainError('CHARACTER_VERSION_CONFLICT')
                result = await session.execute(update(CharacterRow).where(
                    CharacterRow.id == row.id, CharacterRow.updated_at == row.updated_at,
                ).values(payload=deepcopy(character), updated_at=datetime.now(UTC)))
                if getattr(result, 'rowcount', 0) != 1:
                    raise DomainError('CHARACTER_VERSION_CONFLICT')
                return
            await session.merge(
                CharacterRow(
                    id=str(character["id"]),
                    payload=deepcopy(character),
                    updated_at=datetime.now(UTC),
                )
            )

    async def delete(self, character_id: str) -> bool:
        async with self._sessions.begin() as session:
            row = await session.get(CharacterRow, character_id)
            if row is None:
                return False
            await session.delete(row)
            return True
