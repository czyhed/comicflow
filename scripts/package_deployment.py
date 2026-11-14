"""Export clean split repositories without touching Git history or local runtime data.

Usage: uv run python scripts/package_deployment.py --output var/releases/NAME
The output must not already exist. Nothing is pushed or deployed by this script.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {
    "node_modules", "dist", "__pycache__", ".git", "test-results",
    "playwright-report", "acceptance-local", ".venv",
}
LOCAL_DIAGNOSTICS = {
    'frontend/test-debug.spec.ts',
    'frontend/tests/e2e/aa-debug.spec.ts',
    'frontend/tests/e2e/zz-visual-snapshots.spec.ts',
}
# Backend fixtures and migration manifests include JSON. Keep the source
# whitelist explicit while ensuring those files travel with Drone's test gate.
SOURCE_SUFFIXES = {".py", ".mako", ".md", ".txt", ".yaml", ".yml", ".json"}
WEB_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".css", ".html", ".json", ".svg"}


def copy_file(source: str, destination: Path, target: str | None = None) -> None:
    output = destination / (target or source)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / source, output)


def copy_sources(source: str, destination: Path, suffixes: set[str]) -> None:
    for path in sorted((ROOT / source).rglob("*")):
        if not path.is_file() or EXCLUDED.intersection(path.relative_to(ROOT).parts):
            continue
        if path.relative_to(ROOT).as_posix() in LOCAL_DIAGNOSTICS:
            continue
        if path.suffix not in suffixes or path.name.startswith(".env"):
            continue
        if path.name.endswith(".d.ts") and path.name == "vite.config.d.ts":
            continue
        if path.name in {"vite.config.js", "ui-dry.cjs"}:
            continue
        copy_file(path.relative_to(ROOT).as_posix(), destination)


def scan_secrets(destination: Path) -> None:
    # Compare actual local credential values without printing them or uploading them.
    known_secrets: set[str] = set()
    for env_file in ROOT.glob(".env*"):
        if env_file.name.endswith(".example"):
            continue
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            value = value.strip().strip("\"'")
            if sep and re.search(r"KEY|TOKEN|PASSWORD|SECRET", name) and len(value) >= 16:
                if value != "comicflow_dev_only" and not value.startswith(
                    ("replace-", "test-", "mock-", "your-")
                ):
                    known_secrets.add(value)
    patterns = (
        re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{25,}\b"),
        re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    )
    suspicious = []
    for path in destination.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig")
        if any(secret in text for secret in known_secrets) or any(
            pattern.search(text) for pattern in patterns
        ):
            suspicious.append(path.relative_to(destination).as_posix())
    if suspicious:
        raise RuntimeError(f"Potential credentials; do not publish these files: {suspicious}")


def export(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    backend = output / "comicflow"
    web = output / "comicflow-web"
    for repo in (backend, web):
        repo.mkdir()
        for filename in (
            ".gitignore", ".dockerignore", ".gitattributes",
            "docs/DRONE_DEPLOYMENT.md", "docs/DRONE_VERIFICATION.md",
            "docs/DRONE_SUBMISSION_RUNBOOK.md",
            "docs/implementation/manager-pilot-deployment-2026-09-23.md",
            "docs/DATA_MIGRATION_PLAN.md",
            "docs/implementation/persistent-model-console.md",
            "docs/implementation/server-data-connections.md",
        ):
            copy_file(filename, repo)

    for directory in ("backend/src", "backend/migrations", "backend/tests", "skills"):
        copy_sources(directory, backend, SOURCE_SUFFIXES)
    for filename in (
        ".drone.yml", "pyproject.toml", "uv.lock", "alembic.ini", "backend/Dockerfile",
        "scripts/recover_h3_task.py", "deploy/backend.sh", "deploy/compose.backend.yml",
        "deploy/backend.env.example", "deploy/compose.external-data.yml", ".env.server.example",
        "deploy/backend-external.sh", "deploy/compose.external-production.yml",
    ):
        copy_file(filename, backend)
    copy_file("deploy/README.backend.md", backend, "README.md")

    copy_sources("frontend", web, WEB_SUFFIXES)
    copy_file("frontend/Dockerfile", web)
    for filename in (
        "pnpm-lock.yaml", "pnpm-workspace.yaml", "deploy/compose.web.yml",
        "deploy/nginx.conf", "deploy/web.sh",
    ):
        copy_file(filename, web)
    copy_file("deploy/drone.web.yml", web, ".drone.yml")
    copy_file("deploy/README.web.md", web, "README.md")
    (web / "package.json").write_text(json.dumps({
        "name": "comicflow-web-workspace", "private": True, "type": "module",
        "packageManager": "pnpm@11.19.0",
        "scripts": {"dev": "pnpm --dir frontend dev", "build": "pnpm --dir frontend build",
                    "test": "pnpm --dir frontend typecheck && pnpm --dir frontend test:e2e"},
    }, indent=2) + "\n", encoding="utf-8")
    for repo in (backend, web):
        scan_secrets(repo)
        count = sum(path.is_file() for path in repo.rglob("*"))
        print(f"Prepared {repo.name}: {count} files; credential scan passed")
    print(f"Output: {output.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    export(parser.parse_args().output)
