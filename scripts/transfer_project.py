"""Transfer one saved project without merging queues or model configurations."""

import argparse
import asyncio
import json
import re
from pathlib import Path

from migration_tools.bundle import write_json
from migration_tools.selected_project import (
    check_target,
    config,
    export_project,
    import_project,
)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("operation", choices=["export", "check", "import", "verify"])
    cli.add_argument("--config", type=Path, required=True)
    cli.add_argument("--bundle", type=Path, required=True)
    cli.add_argument("--project-id")
    cli.add_argument("--confirm-target", help="Identity hash returned by check")
    cli.add_argument("--backup", type=Path, help="New private target logical-row backup")
    cli.add_argument("--report", type=Path, required=True)
    return cli


async def main(args):
    if args.report.exists():
        raise ValueError("REPORT_EXISTS")
    cfg = config(args.config)
    if args.operation == "export":
        if not args.project_id:
            raise ValueError("PROJECT_ID_REQUIRED")
        manifest = await export_project(cfg, args.project_id, args.bundle)
        result = {
            "projectId": manifest["projectId"],
            "objectCount": len(manifest["objects"]),
            "objectBytes": sum(o["size"] for o in manifest["objects"]),
            "completed": True,
        }
    elif args.operation == "import":
        if not args.backup or not args.confirm_target:
            raise ValueError("BACKUP_AND_TARGET_REQUIRED")
        if args.backup.exists():
            raise ValueError("BACKUP_EXISTS")
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        result = await import_project(cfg, args.bundle, args.backup, args.confirm_target)
    else:
        result = await check_target(cfg, args.bundle)
        if args.operation == "verify":
            if any(p["insert"] for p in result["rows"].values()) or result["objects"]["insert"]:
                raise ValueError("TARGET_INCOMPLETE")
            result["completed"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        asyncio.run(main(parser().parse_args()))
    except Exception as error:
        message = str(error)
        safe = (
            message
            if isinstance(error, ValueError) and re.fullmatch("[A-Z_]{1,90}", message)
            else "PROJECT_TRANSFER_FAILED"
        )
        print(json.dumps({"error": safe, "exceptionType": type(error).__name__}))
        raise SystemExit(1) from None
