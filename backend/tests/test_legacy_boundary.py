from pathlib import Path


def _is_source_candidate(path: Path) -> bool:
    """Whether a path is part of the checked-in stack rather than local output.

    ``var/`` holds throwaway local command output (PowerShell ``Out-File`` writes
    UTF-16, for example), so decoding it as UTF-8 is not a statement about the
    stack and must not decide this test.
    """
    if not path.is_file():
        return False
    return (
        ".git" not in path.parts
        and "node_modules" not in path.parts
        and "test-results" not in path.parts
        and "playwright-report" not in path.parts
        and ".venv" not in path.parts
        and ".scratch" not in path.parts
        and "var" not in path.parts
        and not ("docs" in path.parts and "superpowers" in path.parts)
        and path.name
        not in {"task-12-migration-evidence.md", "session-handoff.md", "test_legacy_boundary.py"}
        and path.suffix.lower()
        in {
            ".md",
            ".json",
            ".yml",
            ".yaml",
            ".toml",
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".css",
            ".html",
            ".txt",
        }
    )


def test_runtime_output_is_not_scanned_as_stack_source(tmp_path: Path) -> None:
    """A UTF-16 dump in var/ must not turn this gate into a decode error."""
    root = tmp_path / "repo"
    (root / "var").mkdir(parents=True)
    (root / "var" / "prj_state.json").write_bytes(b"\xff\xfe{\x00}\x00")
    (root / "backend").mkdir()
    (root / "backend" / "app.py").write_text("print('ok')", encoding="utf-8")
    assert [path.name for path in root.rglob("*") if _is_source_candidate(path)] == ["app.py"]


def test_active_new_stack_has_no_legacy_runtime_commands() -> None:
    root = Path(__file__).parents[2]
    checked = [path for path in root.rglob("*") if _is_source_candidate(path)]
    forbidden = (
        "test:legacy",
        "dev:legacy",
        "src/dev/start-all.js",
        "src/web/server.js",
        "src/production-pipeline.js",
        "prototype/index.html",
        "scripts/upgrade_",
    )

    references = [
        f"{path.relative_to(root)}:{needle}"
        for path in checked
        for needle in forbidden
        if needle in path.read_text(encoding="utf-8")
    ]
    assert references == []
