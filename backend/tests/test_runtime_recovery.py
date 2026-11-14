import os
import subprocess
import sys
from pathlib import Path

import pytest
from comicflow.api.app import create_app, create_configured_runtime
from comicflow.infrastructure.database import Base, create_session_factory
from comicflow.infrastructure.generation_state import InMemoryGenerationStateStore
from httpx import ASGITransport, AsyncClient


async def _create_schema(database_url: str) -> None:
    engine, _sessions = create_session_factory(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgresql_runtime_project_survives_runtime_recreation_and_is_listed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'comicflow.db'}"
    monkeypatch.setenv("COMICFLOW_RUNTIME", "postgresql")
    monkeypatch.setenv("DATABASE_URL", database_url)
    for name in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    # Test database recovery with a fresh ephemeral state store for each runtime.
    monkeypatch.setattr(
        "comicflow.api.app.RedisGenerationStateStore",
        lambda _url: InMemoryGenerationStateStore(),
    )
    await _create_schema(database_url)

    first_app = create_app(create_configured_runtime())
    async with AsyncClient(
        transport=ASGITransport(app=first_app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "暴雨中的末班车驶入车站，失踪多年的姐姐从车窗后回头",
                "durationSec": 60,
                "mode": "guided",
            },
        )
        assert created.status_code == 201
        project_id = created.json()["project"]["id"]
        generated = await client.post(f"/api/projects/{project_id}/script")
        assert generated.status_code == 200
        confirmed = await client.post(
            f"/api/projects/{project_id}/script/confirm",
            json={"expectedVersion": generated.json()["project"]["version"]},
        )
        assert confirmed.status_code == 200
        uploaded = await client.post(
            f"/api/projects/{project_id}/reference-image",
            files={"file": ("reference.png", b"png-bytes", "image/png")},
        )
        assert uploaded.status_code == 200
        reference_id = uploaded.json()["asset"]["id"]
        automatic = await client.post(
            "/api/projects",
            json={
                "inputType": "story",
                "story": "旧唱片店在台风夜重新亮灯，店主听见未来自己的声音",
                "durationSec": 60,
                "mode": "automatic",
            },
        )
        assert automatic.status_code == 201
        automatic_id = automatic.json()["project"]["id"]
        story_generated = await client.post(f"/api/projects/{automatic_id}/story")
        assert story_generated.status_code == 200
        generated_story_text = story_generated.json()["storyText"]
        assert generated_story_text

    second_app = create_app(create_configured_runtime())
    async with AsyncClient(
        transport=ASGITransport(app=second_app), base_url="http://test"
    ) as client:
        restored = await client.get(f"/api/projects/{project_id}")
        assert restored.status_code == 200
        assert restored.json()["project"]["id"] == project_id
        assert restored.json()["project"]["generationSession"]["projectId"] == project_id
        assert restored.json()["script"]["shots"]
        assert restored.json()["project"]["scriptVersions"]
        assert restored.json()["project"]["referenceImage"]["id"] == reference_id
        automatic_restored = await client.get(f"/api/projects/{automatic_id}")
        assert automatic_restored.status_code == 200
        assert automatic_restored.json()["project"]["generatedStoryText"] == generated_story_text

        listed = await client.get("/api/projects")
        assert listed.status_code == 200
        assert any(item["project"]["id"] == project_id for item in listed.json())


def test_postgresql_app_import_does_not_require_optional_s3_configuration(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'import.db'}"
    environment = os.environ.copy()
    environment.update(
        {
            "COMICFLOW_RUNTIME": "postgresql",
            "DATABASE_URL": database_url,
            "PYTHONPATH": os.pathsep.join(["backend/src", environment.get("PYTHONPATH", "")]),
        }
    )
    for name in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", "import comicflow.api.app"],
        cwd=os.fspath(Path(__file__).resolve().parents[2]),
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_memory_runtime_remains_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMICFLOW_RUNTIME", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    runtime = create_configured_runtime()
    assert runtime.pipeline._repository.__class__.__name__ == "InMemoryProjectRepository"


def test_runtime_defaults_to_postgresql_and_rejects_unknown_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("COMICFLOW_RUNTIME", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    runtime = create_configured_runtime()
    assert runtime.pipeline._repository.__class__.__name__ == "SqlAlchemyProjectRepository"

    monkeypatch.setenv("COMICFLOW_RUNTIME", "unsupported")
    with pytest.raises(ValueError, match="unsupported COMICFLOW_RUNTIME"):
        create_configured_runtime()


@pytest.mark.asyncio
async def test_import_entries_create_recoverable_source_projects() -> None:
    from comicflow.domain.models import CreateProject
    from comicflow.infrastructure.memory import create_memory_runtime

    runtime = create_memory_runtime()
    for mode in ("import_story", "import_script"):
        created = await runtime.pipeline.create_project(
            CreateProject(
                input_type="story",
                story="第一场：雨夜车站。主角追上末班车并发现一张旧车票。",
                duration_sec=60,
                mode=mode,
            )
        )
        project = created["project"]
        assert project["input"]["mode"] == mode
        assert project["generatedStoryText"]
        assert project["stage"] == "story-generated"
