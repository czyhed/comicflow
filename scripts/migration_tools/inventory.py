from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import boto3
from botocore.config import Config
from cryptography.fernet import Fernet
from redis import Redis

TABLES = ('alembic_version', 'characters', 'image_generation_jobs', 'model_registry_versions',
          'outbox_events', 'project_states', 'video_generation_jobs')
SCHEMA = '0004_image_jobs'
SEQUENCES = ('model_registry_versions_revision_seq',)
TERMINAL = {'succeeded', 'failed', 'cancelled', 'stale', 'completed'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


def load_config(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    for name in ('label', 'database_url', 's3_endpoint', 's3_bucket', 's3_access_key',
                 's3_secret_key', 'redis_url', 'redis_namespace', 'key_file'):
        if not isinstance(value.get(name), str) or not value[name]:
            raise ValueError('CONFIG_REQUIRED_' + name.upper())
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value['redis_namespace']):
        raise ValueError('REDIS_NAMESPACE_REQUIRED')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value['label']):
        raise ValueError('LABEL_INVALID')
    if not value['database_url'].startswith(('postgresql://', 'postgresql+asyncpg://')):
        raise ValueError('POSTGRESQL_REQUIRED')
    prefix = value.get('pg_command', [])
    if not isinstance(prefix, list) or not all(isinstance(s, str) for s in prefix):
        raise ValueError('PG_COMMAND_INVALID')
    return value


async def connect(config):
    uri = config['database_url'].replace('+asyncpg', '')
    if urlsplit(uri).query:
        raise ValueError('DATABASE_URL_OPTIONS_UNSUPPORTED')
    conn = await asyncpg.connect(uri, timeout=15, ssl=config.get('pg_sslmode', 'prefer'))
    for typ in ('json', 'jsonb'):
        await conn.set_type_codec(typ, encoder=json.dumps, decoder=json.loads, schema='pg_catalog')
    return conn


def s3(config):
    return boto3.client('s3', endpoint_url=config['s3_endpoint'],
                        region_name=config.get('s3_region', 'us-east-1'),
                        aws_access_key_id=config['s3_access_key'],
                        aws_secret_access_key=config['s3_secret_key'],
                        config=Config(connect_timeout=10, read_timeout=60,
                                      retries={'max_attempts': 0}))


def media_references(value, path='$'):
    """All retained references, not just valid assets. Never copy URLs into reports."""
    keys, unresolved = set(), []
    if isinstance(value, dict):
        exports = value.get('objectKeys') or {}
        for name, item in value.items():
            where = f'{path}.{name}'
            if name.lower().endswith('objectkey') and isinstance(item, str) and item:
                keys.add(item)
            elif name == 'objectKeys' and isinstance(item, dict):
                keys.update(k for k in item.values() if isinstance(k, str) and k)
            elif name == 'downloads' and isinstance(item, dict):
                for filename in item:
                    if not exports.get(filename):
                        unresolved.append(f'{where}.{filename}:url-only')
            elif name.lower().endswith('url') and item:
                # Provider endpoints are configuration, not media.
                if name in {'baseUrl', 'endpointUrl'}:
                    continue
                paired = name[:-3] + 'ObjectKey' if name != 'url' else 'objectKey'
                if not value.get(paired) and not (
                    name in {'downloadUrl', 'videoUrl', 'audioUrl', 'imageUrl'}
                    and value.get('objectKey')
                ):
                    unresolved.append(f'{where}:url-only')
            elif name in {'localPath', 'filePath', 'outputPath', 'directory'} and item:
                if not exports and not value.get('objectKey'):
                    unresolved.append(f'{where}:local-file')
            else:
                found, issues = media_references(item, where)
                keys.update(found)
                unresolved.extend(issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found, issues = media_references(item, f'{path}[{index}]')
            keys.update(found)
            unresolved.extend(issues)
    return keys, unresolved


def classify_jobs(rows):
    counts, blockers = Counter(), []
    for row in rows:
        payload = row['payload']
        status = payload.get('status', 'unknown')
        counts[status] += 1
        if status not in TERMINAL or row.get('active_slot'):
            blockers.append(row['id'])
    return dict(counts), blockers


async def database_inventory(conn, key):
    relations = await conn.fetch("""SELECT n.nspname, c.relname, c.relkind::text AS relkind
        FROM pg_class c
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
        AND c.relkind IN ('r','p','v','m','S','f')""")
    names = sorted((r['nspname'], r['relname'], r['relkind']) for r in relations)
    expected = [('public', table, 'r') for table in TABLES]
    expected.extend(('public', sequence, 'S') for sequence in SEQUENCES)
    if names != sorted(expected):
        raise ValueError('DATABASE_TABLE_SET_UNSUPPORTED')
    schema = await conn.fetchval('select version_num from alembic_version')
    if schema != SCHEMA:
        raise ValueError('DATABASE_SCHEMA_UNSUPPORTED')
    fernet = Fernet(key)
    tables, refs, unresolved, blockers, jobs = {}, set(), [], [], {}
    credentials = 0
    for table in TABLES:
        rows = [dict(row) for row in await conn.fetch(f'SELECT * FROM "{table}"')]
        hashes = sorted(digest(row) for row in rows)
        tables[table] = {'rows': len(rows), 'sha256': digest(hashes)}
        if table == 'model_registry_versions':
            for row in rows:
                for connection in row['payload'].get('connections', []):
                    if connection.get('encryptedKey'):
                        fernet.decrypt(connection['encryptedKey'].encode())
                        credentials += 1
        else:
            for row in rows:
                found, issues = media_references(row.get('payload', {}), f'{table}:{row.get("id")}')
                refs.update(found)
                unresolved.extend(issues)
        if table in {'video_generation_jobs', 'image_generation_jobs'}:
            jobs[table], active = classify_jobs(rows)
            blockers.extend(f'{table}:{item}:unfinished' for item in active)
        if table == 'outbox_events':
            pending = sum(r['status'] != 'published' or not r['published_at'] for r in rows)
            if pending:
                blockers.append(f'outbox:unpublished:{pending}')
        if table == 'project_states':
            for row in rows:
                payload = row['payload']
                for job in payload.get('jobs', []):
                    if job.get('status') not in TERMINAL:
                        blockers.append(f'project:{row["id"]}:legacy-job-unfinished')
                session = payload.get('project', {}).get('generationSession') or {}
                if session.get('status') in {'running', 'queued', 'generating', 'pending'}:
                    blockers.append(f'project:{row["id"]}:session-active')
    sequences = {name: dict(await conn.fetchrow(f'SELECT last_value, is_called FROM "{name}"'))
                 for name in SEQUENCES}
    return {'schema': schema, 'tables': tables, 'sequences': sequences, 'references': sorted(refs),
            'unresolvedMedia': sorted(unresolved), 'jobs': jobs, 'blockers': blockers,
            'encryptedCredentialsChecked': credentials,
            'keyFingerprint': hashlib.sha256(key).hexdigest()}


def redis_inventory(config):
    client = Redis.from_url(config['redis_url'], socket_timeout=10, decode_responses=True)
    result, blockers = Counter(), []
    try:
        for key in client.scan_iter(match=config['redis_namespace'] + ':*'):
            kind = client.type(key)
            category = 'other'
            if ':result:' in key:
                category = 'result-cache'
            elif ':generation:events:' in key:
                category = 'event-cache'
            elif ':broker:_kombu.binding.' in key and kind == 'set':
                category = 'broker-binding'
            elif ':generation:' in key and kind == 'string':
                state = json.loads(client.get(key) or '{}')
                category = 'generation-state'
                if state.get('status') not in TERMINAL:
                    blockers.append('redis:unfinished-generation-state')
            else:
                blockers.append('redis:queue-unacked-lock-or-unclassified')
            result[category] += 1
    finally:
        client.close()
    return {'namespace': config['redis_namespace'], 'categories': dict(result),
            'keys': sum(result.values()), 'blockers': sorted(set(blockers)), 'copied': False}


def object_inventory(config, destination=None):
    client, bucket = s3(config), config['s3_bucket']
    if client.get_bucket_versioning(Bucket=bucket).get('Status'):
        raise ValueError('VERSIONED_BUCKET_UNSUPPORTED')
    if client.list_multipart_uploads(Bucket=bucket, MaxUploads=1).get('Uploads'):
        raise ValueError('SOURCE_MULTIPART_UPLOAD_EXISTS')
    entries = []
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket):
        for item in page.get('Contents', []):
            key = item['Key']
            response = client.get_object(Bucket=bucket, Key=key)
            filename = 'objects/' + hashlib.sha256(key.encode()).hexdigest()
            output = (destination / filename).open('xb') if destination else None
            checksum, size = hashlib.sha256(), 0
            try:
                while chunk := response['Body'].read(1024 * 1024):
                    checksum.update(chunk)
                    size += len(chunk)
                    if output:
                        output.write(chunk)
            finally:
                response['Body'].close()
                if output:
                    output.close()
            metadata = {name: response[name] for name in (
                'ContentType', 'Metadata', 'CacheControl', 'ContentDisposition',
                'ContentEncoding', 'ContentLanguage', 'Expires'
            ) if name in response}
            if metadata.get('Expires'):
                metadata['Expires'] = metadata['Expires'].isoformat()
            tags = client.get_object_tagging(Bucket=bucket, Key=key).get('TagSet', [])
            entries.append({'key': key, 'file': filename, 'size': size,
                            'sha256': checksum.hexdigest(), 'metadata': metadata,
                            'tags': sorted(tags, key=lambda t: t['Key'])})
    return sorted(entries, key=lambda e: e['key'])


async def inventory(config, conn=None, destination=None, *, include_projects=False):
    own = conn is None
    if own:
        conn = await connect(config)
    try:
        key = (await asyncio.to_thread(Path(config['key_file']).read_bytes)).strip()
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            data = await database_inventory(conn, key)
            if include_projects:
                from .projects import read_project_rows
                project_rows = await read_project_rows(conn)
        objects = await asyncio.to_thread(object_inventory, config, destination)
        redis = await asyncio.to_thread(redis_inventory, config)
        missing = sorted(set(data['references']) - {item['key'] for item in objects})
        report = {'label': config['label'], 'database': data, 'objects': objects, 'redis': redis,
                'blockers': data['blockers'] + data['unresolvedMedia'] + redis['blockers']
                + [f'missing-object:{key}' for key in missing]}
        if include_projects:
            from .projects import project_report
            report['projects'] = project_report(*project_rows, {item['key'] for item in objects})
        return report
    finally:
        if own:
            await conn.close()
