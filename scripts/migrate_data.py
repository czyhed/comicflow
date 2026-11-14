"""Run with explicit private config; this CLI never reads .env or starts consumers."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from migration_tools.bundle import backup, restore, verify, write_json
from migration_tools.inventory import inventory, load_config


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('operation', choices=['inventory', 'backup', 'restore', 'verify'])
    result.add_argument('--config', type=Path, required=True)
    result.add_argument('--bundle', type=Path)
    result.add_argument('--report', type=Path, required=True, help='New private JSON report file')
    result.add_argument('--key-backup', type=Path, help='New key file OUTSIDE bundle')
    result.add_argument('--writers-stopped', action='store_true',
                        help='Operator asserts API/Worker/Beat and other writers are stopped')
    result.add_argument('--confirm-target', help='Exact target label from explicit config')
    result.add_argument('--projects', action='store_true',
                        help='Include read-only per-project classification (inventory only)')
    return result


async def run(args):
    if args.report.exists():
        raise ValueError('REPORT_EXISTS')
    config = load_config(args.config)
    if args.projects and args.operation != 'inventory':
        raise ValueError('PROJECT_REPORT_INVENTORY_ONLY')
    if args.operation != 'inventory' and not args.bundle:
        raise ValueError('BUNDLE_REQUIRED')
    if args.operation == 'inventory':
        result = await inventory(config, include_projects=args.projects)
    elif args.operation == 'backup':
        if not args.key_backup:
            raise ValueError('SEPARATE_KEY_BACKUP_REQUIRED')
        result = await backup(config, args.bundle, args.key_backup, args.writers_stopped)
    elif args.operation == 'restore':
        result = await restore(config, args.bundle, args.confirm_target, args.writers_stopped)
    else:
        result = await verify(config, args.bundle)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.report, result)
    print(json.dumps({'operation': args.operation, 'completed': True,
                      'blockerCount': len(result.get('blockers', []))}))
    return 2 if result.get('blockers') else 0


if __name__ == '__main__':
    try:
        raise SystemExit(asyncio.run(run(parser().parse_args())))
    except Exception as error:
        # Never print URLs, credentials, database rows or external client exception text.
        message = str(error)
        safe = message if isinstance(error, ValueError) and re.fullmatch(r'[A-Z_]{1,89}', message) \
            else 'MIGRATION_OPERATION_FAILED'
        print(json.dumps({'error': safe, 'exceptionType': type(error).__name__}))
        raise SystemExit(1) from None
