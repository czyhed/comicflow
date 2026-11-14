"""Resolve Compose with synthetic credentials only; never contact a Docker daemon."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = ROOT / "deploy/compose.external-data.yml"
RUNTIME_SERVICES = ("api", "worker", "beat", "migrate")
VALUES = {
    "DATABASE_URL": "postgresql+asyncpg://fixture:fixture@db.example.invalid:5432/comicflow",
    "REDIS_URL": "redis://:fixture@redis.example.invalid:6379/3",
    "COMICFLOW_REDIS_NAMESPACE": "comicflow-config-fixture",
    "S3_ENDPOINT": "https://s3.example.invalid",
    "S3_PUBLIC_ENDPOINT": "https://media.example.invalid",
    "S3_REGION": "test-region",
    "S3_BUCKET": "comicflow-fixture",
    "S3_ACCESS_KEY_ID": "fixture-access",
    "S3_SECRET_ACCESS_KEY": "fixture-secret-$literal",
    "EXPORT_DOWNLOAD_SECRET": "fixture-export-secret",
    "MODEL_CONFIG_ENCRYPTION_KEY": "",
}
REQUIRED = tuple(key for key in VALUES if key not in {
    "S3_REGION", "MODEL_CONFIG_ENCRYPTION_KEY",
})


def compose(directory: Path, filename: str, *args: str) -> subprocess.CompletedProcess[str]:
    if not shutil.which("docker"):
        pytest.skip("Docker Compose CLI is required for offline config validation")
    # Never inherit the developer's provider/connection/Compose overrides.
    environment = {key: value for key, value in os.environ.items() if key.upper() in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME",
        "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "APPDATA", "LOCALAPPDATA",
    }}
    return subprocess.run(
        ["docker", "compose", "--env-file", ".env.server", "-p", "comicflow-config-test",
         "-f", filename, "config", *args],
        cwd=directory, env=environment, capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=False,
    )


def external_fixture(directory: Path, values: dict[str, str]) -> None:
    (directory / "deploy").mkdir()
    shutil.copyfile(EXTERNAL, directory / "deploy/compose.external-data.yml")
    (directory / ".env.server").write_text(
        "\n".join(f"{key}='{value}'" for key, value in values.items()), encoding="utf-8",
    )


def test_external_runtime_uses_one_target_without_implicit_workers(tmp_path: Path) -> None:
    external_fixture(tmp_path, VALUES)
    # The ordinary .env must not be read by this workflow.
    (tmp_path / ".env").write_text("DATABASE_URL=wrong-local-target\n", encoding="utf-8")
    result = compose(tmp_path, "deploy/compose.external-data.yml", "--format", "json")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert set(services) == {"api"}  # No local infrastructure, migration, worker or beat.
    assert services["api"].get("depends_on", {}) == {}
    assert services["api"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert services["api"]["ports"][0]["published"] == "18002"


def test_all_runtime_processes_share_external_config(tmp_path: Path) -> None:
    external_fixture(tmp_path, VALUES)
    # Explicit service selection includes profiled services without starting them.
    result = compose(tmp_path, "deploy/compose.external-data.yml", "--format", "json",
                     *RUNTIME_SERVICES)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert set(services) == set(RUNTIME_SERVICES)
    for name in RUNTIME_SERVICES:
        service = services[name]
        assert service.get("depends_on", {}) == {}
        env = service["environment"]
        for key, value in VALUES.items():
            # Compose config serializes literal dollars as $$ for safe re-reading.
            assert env[key].replace("$$", "$") == value, (name, key)
        assert env["COMICFLOW_RUNTIME"] == "postgresql"
        assert env["MODEL_CONFIG_KEY_FILE"] == "/app/var/config/model-config.key"
    for name in ("worker", "beat", "migrate"):
        assert services[name]["profiles"]
    assert services["migrate"]["restart"] == "no"


@pytest.mark.parametrize("key", REQUIRED)
@pytest.mark.parametrize("empty", [False, True])
def test_missing_or_empty_target_rejected(tmp_path: Path, key: str, empty: bool) -> None:
    values = {k: v for k, v in VALUES.items() if k != key}
    if empty:
        values[key] = ""
    external_fixture(tmp_path, values)
    result = compose(tmp_path, "deploy/compose.external-data.yml", "--quiet")
    assert result.returncode != 0
    assert key in result.stderr


def test_bundled_local_defaults_unchanged(tmp_path: Path) -> None:
    shutil.copyfile(ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    (tmp_path / ".env.server").write_text("", encoding="utf-8")
    result = compose(tmp_path, "docker-compose.yml", "--format", "json")
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in RUNTIME_SERVICES:
        assert services[name]["environment"]["DATABASE_URL"] == (
            "postgresql+asyncpg://comicflow:comicflow_dev_only@postgres:5432/comicflow"
        )
    for name in ("api", "worker", "beat"):
        assert services[name]["environment"]["REDIS_URL"] == "redis://redis:6379/0"
        assert services[name]["environment"]["S3_ENDPOINT"] == "http://object-store:9000"
    assert "migrate" in services["api"]["depends_on"]


def test_server_template_has_no_ready_to_use_credentials() -> None:
    text = (ROOT / ".env.server.example").read_text(encoding="utf-8")
    values = dict(line.split("=", 1) for line in text.splitlines()
                  if line and not line.startswith("#") and "=" in line)
    assert all(values[key] == "" for key in REQUIRED)


def test_optional_settings_and_model_key_reach_all_processes(tmp_path: Path) -> None:
    values = {**VALUES, "EXTERNAL_API_PORT": "18009", "TEXT_PROVIDER_TIMEOUT_MS": "90000",
              "MODEL_CONFIG_ENCRYPTION_KEY": "fixture-key-for-config-only"}
    external_fixture(tmp_path, values)
    result = compose(tmp_path, "deploy/compose.external-data.yml", "--format", "json",
                     *RUNTIME_SERVICES)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    assert services["api"]["ports"][0]["published"] == "18009"
    for name in RUNTIME_SERVICES:
        env = services[name]["environment"]
        assert env["TEXT_PROVIDER_TIMEOUT_MS"] == "90000"
        assert env["MODEL_CONFIG_ENCRYPTION_KEY"] == values["MODEL_CONFIG_ENCRYPTION_KEY"]
        assert any(v["target"] == "/app/var/config" and v["source"] == "model-config"
                   for v in services[name]["volumes"])


def test_external_file_required_even_if_host_values_exist(tmp_path: Path) -> None:
    external_fixture(tmp_path, VALUES)
    (tmp_path / ".env.server").unlink()
    result = compose(tmp_path, "deploy/compose.external-data.yml", "--quiet")
    assert result.returncode != 0
    assert ".env.server" in result.stderr


def test_bundled_server_defaults_unchanged(tmp_path: Path) -> None:
    (tmp_path / "deploy").mkdir()
    shutil.copyfile(ROOT / "deploy/compose.backend.yml",
                    tmp_path / "deploy/compose.backend.yml")
    (tmp_path / "deploy/runtime.env").write_text("", encoding="utf-8")
    (tmp_path / ".env.server").write_text(
        "POSTGRES_PASSWORD=fixture-pg\nMINIO_ROOT_USER=fixture-minio\n"
        "MINIO_ROOT_PASSWORD=fixture-s3\nEXPORT_DOWNLOAD_SECRET=fixture-export\n"
        "S3_PUBLIC_ENDPOINT=https://media.example.invalid\n", encoding="utf-8",
    )
    result = compose(tmp_path, "deploy/compose.backend.yml", "--format", "json",
                     *RUNTIME_SERVICES)
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    for name in RUNTIME_SERVICES:
        env = services[name]["environment"]
        assert env["DATABASE_URL"] == (
            "postgresql+asyncpg://comicflow:fixture-pg@postgres:5432/comicflow"
        )
        assert env["REDIS_URL"] == "redis://redis:6379/0"
        assert env["S3_ENDPOINT"] == "http://object-store:9000"
