"""Synthetic migration rehearsal; owns only comicflow-migration-rehearsal services.

Run: uv run python -X utf8 tests/integration/verify_migration_runtime.py
No business configuration, volumes, API or consumers are used. The Python controller
connects only to random loopback ports; services share an internal Docker network.
"""
# The standalone controller inserts the repository paths before importing helpers.
# Blocking local file operations here are test setup, not application request handlers.
# ruff: noqa: E402, ASYNC240
from __future__ import annotations

import asyncio
import io
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend/src'))

import httpx
from cryptography.fernet import Fernet
from migration_tools.bundle import backup, restore
from migration_tools.inventory import connect, inventory, s3
from PIL import Image
from redis import Redis

PROJECT = 'comicflow-migration-rehearsal'
OUT = ROOT / 'var/verification' / ('migration-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
SAFE_ENV = {k: v for k, v in os.environ.items() if k.upper() in {
    'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'USERPROFILE', 'HOME',
    'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA', 'APPDATA', 'LOCALAPPDATA',
}}
SAFE_ENV.update(PYTHONPATH=str(ROOT / 'backend/src'), AWS_EC2_METADATA_DISABLED='true',
                PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')


def command(args, *, env=None, binary=False):
    result = subprocess.run(args, cwd=ROOT, env=env or SAFE_ENV, capture_output=True,
                            timeout=180)
    if result.returncode:
        (OUT / 'failed-command.txt').write_bytes(result.stdout + result.stderr)
        raise RuntimeError('REHEARSAL_COMMAND_FAILED:' + str(args[:2]) + ':'
                           + result.stderr.decode('utf-8', errors='replace')[-1600:])
    return result.stdout if binary else result.stdout.decode('utf-8').strip()


def compose(*args):
    return command(['docker', 'compose', '--env-file', str(OUT / 'empty.env'), '-p', PROJECT,
                    '-f', 'tests/integration/migration-runtime.compose.yml', *args])


def cli(operation, config_file, *args, expected=0):
    result = subprocess.run([sys.executable, '-X', 'utf8', 'scripts/migrate_data.py', operation,
                             '--config', str(config_file), *map(str, args)], cwd=ROOT,
                            env=SAFE_ENV, capture_output=True, timeout=180)
    stdout = result.stdout.decode('utf-8').strip()
    assert result.returncode == expected, (operation, result.returncode, stdout,
                                           result.stderr.decode('utf-8')[:400])
    return json.loads(stdout)


async def expect_error(code, coroutine):
    try:
        await coroutine
    except ValueError as error:
        assert str(error) == code, str(error)
        return code
    raise AssertionError('Expected ' + code)


async def seed(config):
    conn = await connect(config)
    now = datetime.now(UTC)
    try:
        for db in ('migration_target', 'migration_partial'):
            await conn.execute(f'CREATE DATABASE {db}')
        project = {'id': 'prj_migration', 'version': 1, 'stage': 'exported',
                   'script': {'title': '迁移合成样本', 'shots': [{'id': 's1', 'title': '样本'}]},
                   'visualAssets': [
                       {'id': name, 'shotId': 's1', 'objectKey': name + '.mp4',
                        'mediaType': 'video', 'valid': name == 'current',
                        **({'status': 'candidate'} if name == 'candidate' else {}),
                        'lastFrameObjectKey': 'tail.png'}
                       for name in ('current', 'candidate', 'historical')],
                   'exportManifest': {'files': ['video.mp4', 'cover.jpg', 'subtitles.srt'],
                                      'objectKeys': {'video.mp4': 'export.mp4',
                                                     'cover.jpg': 'cover.png',
                                                     'subtitles.srt': 'subtitles.srt'}}}
        await conn.execute('INSERT INTO project_states VALUES ($1,$2,$3)', 'prj_migration',
                           {'project': project, 'guestSession': None, 'jobs': []}, now)
        await conn.execute('INSERT INTO characters VALUES ($1,$2,$3)', 'chr_migration',
                           {'id': 'chr_migration', 'referenceBoard': {
                               'status': 'approved', 'objectKey': 'board.png'},
                            'referenceBoardCandidate': {'objectKey': 'candidate-board.png'}}, now)
        cipher = Fernet(Path(config['key_file']).read_bytes())
        for revision in (1, 2):
            await conn.execute('INSERT INTO model_registry_versions VALUES ($1,$2)', revision,
                               {'revision': revision, 'connections': [{'id': 'synthetic',
                                 'name': 'Synthetic', 'baseUrl': 'https://model.invalid',
                                 'encryptedKey': cipher.encrypt(b'synthetic-api-key').decode()}],
                                'models': [], 'bindings': {}})
        for table in ('video_generation_jobs', 'image_generation_jobs'):
            await conn.execute(f'INSERT INTO {table} VALUES ($1,$2,$3,$4,$5,$6)',
                               table + '-1', 'prj_migration', table + '-operation', None, 1,
                               {'status': 'succeeded', 'modelConfigRevision': 1,
                                'result': {'asset': {'objectKey': 'historical.mp4'}}})
        await conn.execute('INSERT INTO outbox_events VALUES ($1,$2,$3,$4,$5,$6)',
                           'evt_migration', 'production.video.queued',
                           {'jobId': 'video_generation_jobs-1'}, 'published', now, now)
    finally:
        await conn.close()
    video = command(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'ffmpeg',
                     'comicflow-api:latest', '-v', 'error', '-f', 'lavfi', '-i',
                     'color=c=blue:s=96x128:r=10:d=1', '-c:v', 'libx264', '-pix_fmt',
                     'yuv420p', '-movflags', 'frag_keyframe+empty_moov', '-f', 'mp4', 'pipe:1'],
                    binary=True)
    image = io.BytesIO()
    Image.new('RGB', (96, 64), 'blue').save(image, format='PNG')
    objects = {name + '.mp4': (video, 'video/mp4')
               for name in ('current', 'candidate', 'historical', 'export')}
    objects.update({name + '.png': (image.getvalue(), 'image/png')
                    for name in ('tail', 'cover', 'board', 'candidate-board')})
    objects['subtitles.srt'] = (b'1\n00:00:00,000 --> 00:00:01,000\nSynthetic\n',
                                'application/x-subrip')
    client = s3(config)
    for key, (body, mime) in objects.items():
        client.put_object(Bucket=config['s3_bucket'], Key=key, Body=body, ContentType=mime,
                          Metadata={'purpose': 'synthetic-rehearsal'}, Tagging='scope=test',
                          CacheControl='private, max-age=60')
    return objects


async def exercise(source, target, partial, files):
    errors = []
    initial = await inventory(source)
    assert initial['blockers'] == [], initial['blockers']
    assert initial['database']['encryptedCredentialsChecked'] == 2
    conn = await connect(source)
    try:
        await conn.execute('CREATE SCHEMA unrelated')
        await conn.execute('CREATE TABLE unrelated.sentinel (id integer)')
        errors.append(await expect_error('DATABASE_TABLE_SET_UNSUPPORTED', inventory(source)))
        await conn.execute('DROP TABLE unrelated.sentinel')
        await conn.execute('DROP SCHEMA unrelated')
        await conn.execute("UPDATE video_generation_jobs SET payload=json_build_object("
                           "'status','unknown')")
        errors.append(await expect_error('SOURCE_NOT_READY', backup(
            source, OUT / 'blocked', OUT / 'blocked.key', True)))
        assert not (OUT / 'blocked').exists()
        await conn.execute('UPDATE video_generation_jobs SET payload=$1',
                           {'status': 'succeeded', 'modelConfigRevision': 1,
                            'result': {'asset': {'objectKey': 'historical.mp4'}}})
        await conn.execute("UPDATE outbox_events SET status='pending'")
        assert (await inventory(source))['blockers'] == ['outbox:unpublished:1']
        await conn.execute("UPDATE outbox_events SET status='published'")
    finally:
        await conn.close()
    redis = Redis.from_url(source['redis_url'])
    redis.rpush(source['redis_namespace'] + ':broker:' + source['redis_namespace'] + '.tasks',
                'synthetic queued message')
    assert (await inventory(source))['redis']['blockers']
    # Only this rehearsal's synthetic key is removed, never business queues.
    redis.delete(source['redis_namespace'] + ':broker:' + source['redis_namespace'] + '.tasks')
    redis.set(source['redis_namespace'] + ':result:celery-task-meta-done', '{}')
    assert not (await inventory(source))['blockers']
    source_client = s3(source)
    missing_key = 'candidate-board.png'
    source_client.delete_object(Bucket=source['s3_bucket'], Key=missing_key)
    assert 'missing-object:' + missing_key in (await inventory(source))['blockers']
    body, mime = files[missing_key]
    source_client.put_object(Bucket=source['s3_bucket'], Key=missing_key, Body=body,
                            ContentType=mime, Metadata={'purpose': 'synthetic-rehearsal'},
                            Tagging='scope=test', CacheControl='private, max-age=60')
    paths = {}
    for config in (source, target, partial):
        path = OUT / (config['label'] + '.json')
        path.write_text(json.dumps(config), encoding='utf-8')
        paths[config['label']] = path
    source_file, target_file = paths[source['label']], paths[target['label']]
    # CLI is invoked from a worker thread while the controller's event loop remains responsive.
    await asyncio.to_thread(cli, 'inventory', source_file, '--report', OUT / 'source-report.json')
    bundle = OUT / 'bundle'
    await asyncio.to_thread(cli, 'backup', source_file, '--bundle', bundle, '--report',
                            OUT / 'backup-report.json', '--key-backup', OUT / 'key-copy.key',
                            '--writers-stopped')
    assert (OUT / 'key-copy.key').read_bytes() == Path(source['key_file']).read_bytes()
    wrong = OUT / 'wrong.key'
    wrong.write_bytes(Fernet.generate_key())
    errors.append(await expect_error('MODEL_KEY_MISMATCH', restore(
        {**target, 'key_file': str(wrong)}, bundle, target['label'], True)))
    damaged = bundle / 'database.dump'
    original_dump = damaged.read_bytes()
    damaged.write_bytes(original_dump + b'damage')
    errors.append(await expect_error('BACKUP_CHECKSUM_MISMATCH', restore(
        target, bundle, target['label'], True)))
    damaged.write_bytes(original_dump)
    errors.append(await expect_error('SOURCE_TARGET_OVERLAP', restore(
        source, bundle, source['label'], True)))
    conn = await connect(target)
    try:
        await conn.execute('CREATE TABLE sentinel (id integer)')
        errors.append(await expect_error('TARGET_DATABASE_NOT_EMPTY', restore(
            target, bundle, target['label'], True)))
        await conn.execute('DROP TABLE sentinel')
    finally:
        await conn.close()
    client = s3(target)
    client.put_object(Bucket=target['s3_bucket'], Key='sentinel', Body=b'preserve')
    errors.append(await expect_error('TARGET_BUCKET_NOT_EMPTY', restore(
        target, bundle, target['label'], True)))
    saved_sentinel = client.get_object(Bucket=target['s3_bucket'], Key='sentinel')['Body']
    assert saved_sentinel.read() == b'preserve'
    saved_sentinel.close()
    client.delete_object(Bucket=target['s3_bucket'], Key='sentinel')
    redis.set(target['redis_namespace'] + ':existing', 'preserve')
    errors.append(await expect_error('TARGET_REDIS_NAMESPACE_NOT_EMPTY', restore(
        target, bundle, target['label'], True)))
    redis.delete(target['redis_namespace'] + ':existing')
    await asyncio.to_thread(cli, 'restore', target_file, '--bundle', bundle, '--report',
                            OUT / 'restore-report.json', '--confirm-target', target['label'],
                            '--writers-stopped')
    errors.append(await expect_error('TARGET_DATABASE_NOT_EMPTY', restore(
        target, bundle, target['label'], True)))
    await asyncio.to_thread(cli, 'verify', target_file, '--bundle', bundle, '--report',
                            OUT / 'verify-report.json')
    # New signed addresses access all retained images/videos/exports without source URLs.
    async with httpx.AsyncClient(trust_env=False) as http:
        for key, (body, _) in files.items():
            url = client.generate_presigned_url('get_object', Params={
                'Bucket': target['s3_bucket'], 'Key': key}, ExpiresIn=60)
            result = await http.get(url)
            assert result.status_code == 200 and result.content == body
    from comicflow.infrastructure.database import (
        SqlAlchemyProjectRepository,
        create_session_factory,
    )
    from comicflow.production.video_resources import VideoResources
    from comicflow.providers.model_registry import SecretCipher, SqlRegistryRepository
    from comicflow.providers.s3 import S3AssetStore
    for _ in range(2):
        engine, sessions = create_session_factory(target['database_url'])
        try:
            repository = SqlAlchemyProjectRepository(sessions)
            store = S3AssetStore(target['s3_endpoint'], 'us-east-1', target['s3_bucket'],
                                 target['s3_access_key'], target['s3_secret_key'])
            resources = VideoResources(repository, store)
            catalog = await resources.list('prj_migration', None)
            assert {a['status'] for a in catalog['items']} == {'current', 'candidate', 'historical'}
            assert catalog['total'] == 4
            for item in catalog['items']:
                access = await resources.access('prj_migration', item['id'], None)
                assert access
            for revision in (1, 2):
                registry = await SqlRegistryRepository(sessions).load(revision)
                cipher = SecretCipher(path=Path(target['key_file']))
                assert cipher.decrypt(registry['connections'][0]['encryptedKey']) \
                    == 'synthetic-api-key'
        finally:
            await engine.dispose()
    # Inject an object upload failure AFTER the real transaction restored the database.
    from migration_tools import bundle as implementation
    real_s3 = implementation.s3

    class FailingUploads:
        def __init__(self, config):
            self.client = real_s3(config)

        def __getattr__(self, name):
            return getattr(self.client, name)

        def put_object(self, **_kwargs):
            raise ValueError('SYNTHETIC_UPLOAD_FAILURE')

    implementation.s3 = FailingUploads
    try:
        errors.append(await expect_error('SYNTHETIC_UPLOAD_FAILURE', restore(
            partial, bundle, partial['label'], True)))
    finally:
        implementation.s3 = real_s3
    errors.append(await expect_error('TARGET_DATABASE_NOT_EMPTY', restore(
        partial, bundle, partial['label'], True)))
    assert (await inventory(source))['database'] == initial['database']
    assert list(redis.scan_iter(match=target['redis_namespace'] + ':*')) == []
    redis.close()
    # No plaintext key or signed URL may appear in manifest/report output.
    for name in ('manifest.json',):
        content = (bundle / name).read_text(encoding='utf-8')
        assert 'synthetic-api-key' not in content and 'X-Amz-' not in content
        assert Path(source['key_file']).read_text() not in content
    return {'passed': True, 'objects': len(files), 'tables': len(initial['database']['tables']),
            'registryRevisions': 2, 'failureProtections': errors,
            'signedMediaReads': len(files), 'repositoryRecreations': 2,
            'realModelCalls': 0, 'businessDataAccessed': False, 'redisMessagesCopied': 0}


async def main():
    os.environ.clear()
    os.environ.update(SAFE_ENV)
    OUT.mkdir(parents=True)
    (OUT / 'empty.env').write_text('', encoding='utf-8')
    started = time.monotonic()
    try:
        compose('up', '-d', '--wait', '--wait-timeout', '60')
        ports = {service: int(compose('port', 'proxy', str(port)).rsplit(':', 1)[1])
                 for service, port in [('postgres', 15432), ('minio', 19000), ('redis', 16379)]}
        assert all(1024 < port < 65536 for port in ports.values()), 'Ports must be published'
        container = compose('ps', '-q', 'postgres')
        key_file = OUT / 'source.key'
        key_file.write_bytes(Fernet.generate_key())
        prefix = ['docker', 'exec', '-i']
        for name in ('PGHOST', 'PGPORT', 'PGUSER', 'PGPASSWORD', 'PGDATABASE', 'PGSSLMODE',
                     'PGCONNECT_TIMEOUT'):
            prefix.extend(['-e', name])
        prefix.append(container)
        source = {
            'label': 'migration-source', 'database_url':
                f'postgresql://migration:synthetic-migration-only@127.0.0.1:{ports["postgres"]}'
                '/migration_source',
            's3_endpoint': f'http://127.0.0.1:{ports["minio"]}', 's3_bucket': 'migration-source',
            's3_access_key': 'migration', 's3_secret_key': 'synthetic-migration-only',
            'redis_url': f'redis://127.0.0.1:{ports["redis"]}/0',
            'redis_namespace': 'migration-source', 'key_file': str(key_file),
            'pg_command': prefix, 'pg_host': '127.0.0.1', 'pg_port': 5432}
        target = {**source, 'label': 'migration-target', 'database_url':
                  source['database_url'].replace('/migration_source', '/migration_target'),
                  's3_bucket': 'migration-target', 'redis_namespace': 'migration-target'}
        partial = {**target, 'label': 'migration-partial', 'database_url':
                   source['database_url'].replace('/migration_source', '/migration_partial'),
                   's3_bucket': 'migration-partial', 'redis_namespace': 'migration-partial'}
        env = {**SAFE_ENV, 'DATABASE_URL': source['database_url']}
        command([sys.executable, '-m', 'alembic', 'upgrade', 'head'], env=env)
        # Python clients are restricted to loopback; providers cannot be reached.
        getaddrinfo = socket.getaddrinfo

        def local_only(host, *args, **kwargs):
            if host not in {'127.0.0.1', 'localhost', '::1', b'127.0.0.1'}:
                raise AssertionError('Non-local network blocked in migration rehearsal')
            return getaddrinfo(host, *args, **kwargs)

        socket.getaddrinfo = local_only
        try:
            client = s3(source)
            for config in (source, target, partial):
                client.create_bucket(Bucket=config['s3_bucket'])
            files = await seed(source)
            report = await exercise(source, target, partial, files)
            report['elapsedSeconds'] = round(time.monotonic() - started, 2)
            (OUT / 'rehearsal-report.json').write_text(
                json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report, indent=2))
            print('Evidence:', OUT)
        finally:
            socket.getaddrinfo = getaddrinfo
    finally:
        compose('down')  # This exact synthetic project only; no host recursive deletion.


if __name__ == '__main__':
    asyncio.run(main())
