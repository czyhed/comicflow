"""Plan/apply the legacy ComicFlow owner migration; dry-run by default.

The shared ShiploadAI account is the decoded gateway identity
``password:xshipai`` (the workbench sends it URL encoded as
``password%3Axshipai``). Old projects claimed by browser guest ids (``gst_*``)
or magic-link identities (``user_*``) are re-owned by that account so a new
browser can open them.

Examples:
    # Read-only statistics (the default). Safe against production.
    python scripts/migrate_legacy_project_owner.py --database-url postgresql://...

    # Apply after a backup and after API/Worker/Beat writers are stopped.
    python scripts/migrate_legacy_project_owner.py --database-url ... --apply

This CLI never changes anything unless ``--apply`` is present.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / "backend" / "src"

DEFAULT_TARGET_OWNER = "password:xshipai"
DEFAULT_LEGACY_PREFIXES = ("gst_", "user_")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="Async or sync PostgreSQL URL; defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--target",
        default=DEFAULT_TARGET_OWNER,
        help=f"Decoded shared-account identity (default: {DEFAULT_TARGET_OWNER}).",
    )
    parser.add_argument(
        "--legacy-prefix",
        action="append",
        dest="legacy_prefixes",
        help="Owner prefix treated as legacy; repeatable. Defaults to gst_ and user_.",
    )
    parser.add_argument(
        "--skip-unowned",
        action="store_true",
        help="Leave projects whose ownerUserId is null untouched.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the changes. Without this flag the command is a read-only dry run.",
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    if not args.database_url:
        print(json.dumps({
            "error": "DATABASE_URL_REQUIRED",
            "hint": "Pass --database-url or set DATABASE_URL.",
        }, ensure_ascii=False))
        return 2

    if str(SOURCE_ROOT) not in sys.path:
        sys.path.insert(0, str(SOURCE_ROOT))

    from comicflow.identity.legacy_migration import migrate_legacy_owners
    from comicflow.infrastructure.database import (
        SqlAlchemyProjectRepository,
        create_session_factory,
    )

    engine, sessions = create_session_factory(args.database_url)
    try:
        repository = SqlAlchemyProjectRepository(sessions)
        report = await migrate_legacy_owners(
            repository,
            target_owner=args.target,
            legacy_prefixes=tuple(args.legacy_prefixes or DEFAULT_LEGACY_PREFIXES),
            include_unowned=not args.skip_unowned,
            dry_run=not args.apply,
        )
    finally:
        await engine.dispose()

    payload = report.as_dict()
    payload["mode"] = "apply" if args.apply else "dry-run"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not args.apply:
        print(
            "Dry run only. Re-run with --apply after a database backup and with "
            "API/Worker/Beat writers stopped.",
            file=sys.stderr,
        )
    return 1 if report.failed else 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:  # Never print URLs or credentials.
        print(json.dumps({
            "error": "MIGRATION_FAILED",
            "exceptionType": type(error).__name__,
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
