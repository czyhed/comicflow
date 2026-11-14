from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlencode, urlsplit

from .inventory import SCHEMA, connect, database_inventory, digest, inventory, redis_inventory, s3


def checked_file(root, name):
    if (not isinstance(name, str) or not name or ':' in name or '\\' in name
            or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts):
        raise ValueError('BUNDLE_PATH_INVALID')
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('BUNDLE_PATH_INVALID')
    return path


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        stream.write('\n')


def require_safe_inventory(report):
    if report['blockers']:
        raise ValueError('SOURCE_NOT_READY')


def identities(config):
    db = urlsplit(config['database_url'].replace('+asyncpg', ''))
    return {'database': digest([db.hostname, db.port or 5432, db.path]),
            'bucket': digest([config['s3_endpoint'].rstrip('/'), config['s3_bucket']]),
            'redis': digest([config['redis_url'], config['redis_namespace']])}


def pg_command(config, tool, args, path, restore=False):
    """No shell or passwords in argv/logs; Docker prefix can forward PG* by name."""
    uri = urlsplit(config['database_url'].replace('+asyncpg', ''))
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    env.update(PGHOST=config.get('pg_host', uri.hostname),
               PGPORT=str(config.get('pg_port', uri.port or 5432)),
               PGUSER=unquote(uri.username or ''), PGPASSWORD=unquote(uri.password or ''),
               PGDATABASE=unquote(uri.path.lstrip('/')), PGCONNECT_TIMEOUT='15',
               PGSSLMODE=config.get('pg_sslmode', 'prefer'))
    if uri.query:
        # Avoid silently using a different SSL/options policy than the snapshot connection.
        raise ValueError('DATABASE_URL_OPTIONS_UNSUPPORTED')
    command = [*config.get('pg_command', []), tool, *args]
    with path.open('rb' if restore else 'xb') as stream:
        result = subprocess.run(command, env=env, stdin=stream if restore else subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL if restore else stream,
                                stderr=subprocess.PIPE, timeout=config.get('pg_timeout', 600),
                                check=False)
    if result.returncode:
        # pg client errors can include host/user/schema data; expose only operation here.
        raise ValueError('PG_RESTORE_FAILED' if restore else 'PG_DUMP_FAILED')


async def backup(config, directory, key_backup, writers_stopped=False):
    if not writers_stopped:
        raise ValueError('WRITERS_STOPPED_REQUIRED')
    directory = await asyncio.to_thread(Path(directory).resolve)
    key_backup = await asyncio.to_thread(Path(key_backup).resolve)
    if key_backup.is_relative_to(directory) or key_backup.exists():
        raise ValueError('SEPARATE_NEW_KEY_BACKUP_REQUIRED')
    if directory.exists():
        raise ValueError('BACKUP_DESTINATION_EXISTS')
    report = await inventory(config)
    require_safe_inventory(report)
    directory.mkdir(parents=True, mode=0o700)
    (directory / 'objects').mkdir(mode=0o700)
    key = (await asyncio.to_thread(Path(config['key_file']).read_bytes)).strip()
    conn = await connect(config)
    try:
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            snapshot_report = await database_inventory(conn, key)
            if snapshot_report != report['database']:
                raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
            snapshot = await conn.fetchval('SELECT pg_export_snapshot()')
            await asyncio.to_thread(pg_command, config, 'pg_dump', [
                '-Fc', '--no-owner', '--no-acl', '--snapshot=' + snapshot,
            ], directory / 'database.dump')
        copied = await inventory(config, destination=directory)
        if copied != report:
            raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
        # Re-read after object copying to catch changed content, not just changed keys/ETags.
        if await inventory(config) != report:
            raise ValueError('SOURCE_CHANGED_DURING_BACKUP')
        key_backup.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(key_backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(key)
        manifest = {'format': 'comicflow-backup-v1', 'complete': True,
                    'createdAt': datetime.now(UTC).isoformat(), 'source': identities(config),
                    'inventory': report, 'databaseDump': {
                        'file': 'database.dump', 'sha256': file_hash(directory / 'database.dump')},
                    'separateKeyBackup': True}
        write_json(directory / 'manifest.json', manifest)
        return {'complete': True, 'objects': len(report['objects']),
                'tables': report['database']['tables'], 'keyBackedUpSeparately': True}
    finally:
        await conn.close()


def validate_bundle(directory, config):
    directory = Path(directory).resolve()
    manifest = json.loads(checked_file(directory, 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'comicflow-backup-v1' or manifest.get('complete') is not True:
        raise ValueError('BACKUP_INCOMPLETE')
    report = manifest['inventory']
    require_safe_inventory(report)
    if report['database']['schema'] != SCHEMA:
        raise ValueError('DATABASE_SCHEMA_UNSUPPORTED')
    key = Path(config['key_file']).read_bytes().strip()
    if hashlib.sha256(key).hexdigest() != report['database']['keyFingerprint']:
        raise ValueError('MODEL_KEY_MISMATCH')
    entries = [manifest['databaseDump'], *report['objects']]
    names = [entry['file'] for entry in entries]
    keys = [entry['key'] for entry in report['objects']]
    if len(names) != len(set(names)) or len(keys) != len(set(keys)):
        raise ValueError('BUNDLE_DUPLICATE_ENTRY')
    for entry in entries:
        path = checked_file(directory, entry['file'])
        if file_hash(path) != entry['sha256'] or (
            'size' in entry and path.stat().st_size != entry['size']
        ):
            raise ValueError('BACKUP_CHECKSUM_MISMATCH')
    return manifest


async def require_empty_target(config, conn):
    relations = await conn.fetchval("""SELECT count(*) FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
        AND c.relkind IN ('r','p','v','m','S','f')""")
    if relations:
        raise ValueError('TARGET_DATABASE_NOT_EMPTY')
    client, bucket = s3(config), config['s3_bucket']
    if client.get_bucket_versioning(Bucket=bucket).get('Status'):
        raise ValueError('VERSIONED_BUCKET_UNSUPPORTED')
    if client.list_objects_v2(Bucket=bucket, MaxKeys=1).get('KeyCount', 0):
        raise ValueError('TARGET_BUCKET_NOT_EMPTY')
    if client.list_multipart_uploads(Bucket=bucket, MaxUploads=1).get('Uploads'):
        raise ValueError('TARGET_MULTIPART_UPLOAD_EXISTS')
    if redis_inventory(config)['keys']:
        raise ValueError('TARGET_REDIS_NAMESPACE_NOT_EMPTY')


async def verify(config, directory):
    manifest = validate_bundle(directory, config)
    actual = await inventory(config)
    expected = manifest['inventory']
    if actual['database'] != expected['database'] or actual['objects'] != expected['objects']:
        raise ValueError('RESTORE_VERIFICATION_MISMATCH')
    if actual['redis']['keys']:
        raise ValueError('TARGET_REDIS_NAMESPACE_NOT_EMPTY')
    require_safe_inventory(actual)
    return {'verified': True, 'tables': actual['database']['tables'],
            'objects': len(actual['objects']), 'redisMessagesCopied': 0,
            'encryptedCredentialsChecked': actual['database']['encryptedCredentialsChecked']}


async def restore(config, directory, confirm_target, writers_stopped=False):
    if not writers_stopped:
        raise ValueError('WRITERS_STOPPED_REQUIRED')
    if confirm_target != config['label']:
        raise ValueError('TARGET_CONFIRMATION_MISMATCH')
    directory = await asyncio.to_thread(Path(directory).resolve)
    manifest = validate_bundle(directory, config)
    target = identities(config)
    if any(target[name] == manifest['source'][name] for name in ('database', 'bucket', 'redis')):
        raise ValueError('SOURCE_TARGET_OVERLAP')
    conn = await connect(config)
    try:
        if not await conn.fetchval('SELECT pg_try_advisory_lock(710922008)'):
            raise ValueError('TARGET_RESTORE_BUSY')
        await require_empty_target(config, conn)
        await asyncio.to_thread(pg_command, config, 'pg_restore', [
            '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
            # Connection database comes from PGDATABASE; '-' selects stdin.
            '--dbname=' + unquote(urlsplit(config['database_url']).path.lstrip('/')),
        ], checked_file(directory, manifest['databaseDump']['file']), True)
        client, bucket = s3(config), config['s3_bucket']
        for item in manifest['inventory']['objects']:
            metadata = dict(item['metadata'])
            if metadata.get('Expires'):
                metadata['Expires'] = datetime.fromisoformat(metadata['Expires'])
            with checked_file(directory, item['file']).open('rb') as stream:
                client.put_object(Bucket=bucket, Key=item['key'], Body=stream,
                                  IfNoneMatch='*', Tagging=urlencode({
                                      t['Key']: t['Value'] for t in item['tags']}), **metadata)
        result = await verify(config, directory)
        return {**result, 'target': config['label'], 'workersStarted': False}
    finally:
        await conn.close()
