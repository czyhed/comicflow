"""Real PostgreSQL/Redis/S3 and separate API/Worker, with a loopback fake H3.

Run ONLY through video-runtime.compose.yml's internal Docker network. The database,
bucket, queue and key are synthetic. No business .env or existing queue is loaded.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OUT = Path('/verification')
ROOT = Path('/workspace')
PREFIX = 'comicflow_verify_video'


def configure() -> None:
    for key in list(os.environ):
        if key.startswith((
            'COMICFLOW_', 'S3_', 'MINIO_', 'AWS_', 'CELERY_', 'TEXT_', 'VIDEO_',
            'IMAGE_', 'MEDIA_', 'VISUAL_', 'TTS_', 'LIPSYNC_', 'MINIMAX_', 'BAILIAN_',
            'ARK_', 'DOUBAO_', 'DASHSCOPE_', 'PROVIDER_', 'DATABASE_', 'REDIS_',
            'USE_MINIMAX_', 'MODEL_CONFIG_', 'EXPORT_', 'HTTP_PROXY', 'HTTPS_PROXY',
            'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy',
        )):
            del os.environ[key]
    from cryptography.fernet import Fernet
    os.environ.update({
        'COMICFLOW_RUNTIME': 'postgresql', 'PROVIDER_MODE': 'mock',
        'DATABASE_URL': 'postgresql+asyncpg://verify:verification-only@postgres/comicflow_verify',
        'REDIS_URL': 'redis://redis:6379/0', 'COMICFLOW_REDIS_NAMESPACE': PREFIX,
        'S3_ENDPOINT': 'http://minio:9000', 'S3_PUBLIC_ENDPOINT': 'http://minio:9000',
        'S3_BUCKET': 'comicflow-verify', 'S3_ACCESS_KEY_ID': 'verification',
        'S3_SECRET_ACCESS_KEY': 'verification-only', 'S3_REGION': 'us-east-1',
        'AWS_EC2_METADATA_DISABLED': 'true', 'IMAGE_PROVIDER_MODE': 'disabled',
        'USE_MINIMAX_H3': 'true', 'MINIMAX_API_KEY': 'fake-provider-only',
        'MINIMAX_BASE_URL': 'http://127.0.0.1:18093', 'MINIMAX_PROMPT_MODE': 'context-ir',
        'MINIMAX_VIDEO_RESOLUTION': '768P', 'MINIMAX_TIMEOUT_SECONDS': '30',
        'MINIMAX_POLL_INTERVAL_SECONDS': '0.1',
        'MODEL_CONFIG_ENCRYPTION_KEY': Fernet.generate_key().decode(),
        'EXPORT_DOWNLOAD_SECRET': 'isolated-verification-only',
        'EXPORT_OUTPUT_DIR': str(OUT / 'exports'),
    })


class FakeH3(BaseHTTPRequestHandler):
    submissions = 0
    queries = 0
    downloads = 0
    complete = False
    fail_download = True
    payload: dict = {}

    def log_message(self, *_args) -> None:
        pass

    def reply(self, body: bytes, status: int = 200, mime: str = 'application/json') -> None:
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        assert self.path == '/minimax/v2/video_generation', self.path
        cls = type(self)
        cls.submissions += 1
        cls.payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.reply(b'{"task_id":"fake-h3-task-1"}')

    def do_GET(self) -> None:
        cls = type(self)
        if self.path == '/clip.mp4':
            cls.downloads += 1
            assert not self.headers.get('Authorization'), 'Gateway key leaked to download'
            if cls.fail_download:
                self.reply(b'{}', 503)
            else:
                self.reply((OUT / 'fake-h3.mp4').read_bytes(), mime='video/mp4')
            return
        assert self.path == '/minimax/v2/query/video_generation/fake-h3-task-1', self.path
        cls.queries += 1
        self.reply(json.dumps({'task': {
            'status': 'succeeded' if cls.complete else 'running',
            'content': {'url': 'http://127.0.0.1:18093/clip.mp4'},
        }}).encode())


async def verify() -> None:
    import boto3
    import httpx
    from comicflow.infrastructure.database import (
        SqlAlchemyProjectRepository,
        create_session_factory,
    )
    from comicflow.infrastructure.video_jobs import SqlVideoJobStore
    from comicflow.worker.celery_app import publish_to_celery
    from comicflow.worker.outbox import OutboxDispatcher
    from redis import Redis
    from sqlalchemy import text

    assert Path.cwd() == OUT, 'Use the isolated Compose entrypoint'
    assert os.environ['DATABASE_URL'].endswith('@postgres/comicflow_verify')
    logs = []
    processes: list[subprocess.Popen] = []

    def spawn(name: str, args: list[str]) -> subprocess.Popen:
        log = (OUT / f'runtime-{name}.log').open('w')
        logs.append(log)
        proc = subprocess.Popen([sys.executable, *args], stdout=log, stderr=log)
        processes.append(proc)
        return proc

    def stop(proc: subprocess.Popen, *, crash: bool = False) -> None:
        if proc.poll() is None:
            proc.kill() if crash else proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    async def wait_for(fetch, predicate, label: str):
        deadline = time.monotonic() + 40
        last = None
        while time.monotonic() < deadline:
            try:
                last = await fetch()
                if predicate(last):
                    return last
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.2)
        raise AssertionError(f'{label} did not finish: {last}')

    s3 = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'],
        aws_access_key_id='verification', aws_secret_access_key='verification-only',
        region_name='us-east-1')
    s3.create_bucket(Bucket='comicflow-verify')
    assert Redis.from_url(os.environ['REDIS_URL']).ping()
    engine, sessions = create_session_factory(os.environ['DATABASE_URL'])
    repo = SqlAlchemyProjectRepository(sessions)
    store = SqlVideoJobStore(sessions)
    dispatcher = OutboxDispatcher(repo, publish_to_celery)
    api_args = ['-m', 'uvicorn', 'comicflow.api.app:app', '--host', '127.0.0.1', '--port', '18094']
    worker_args = ['-m', 'celery', '-A', 'comicflow.worker.celery_app:celery_app', 'worker',
                   '--pool=solo', '--concurrency=1', '--loglevel=INFO',
                   '-Q', f'{PREFIX}.tasks', '--without-gossip', '--without-mingle']
    try:
        async with engine.connect() as conn:
            schema = (await conn.execute(text('select version_num from alembic_version'))).scalar()
            assert schema == '0004_image_jobs', schema
        api = spawn('api-before', api_args)
        worker = spawn('worker-before', worker_args)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18094', timeout=10) as client:
            await wait_for(lambda: client.get('/health'), lambda r: r.status_code == 200, 'API')
            response = await client.post('/api/projects', json={
                'inputType': 'story', 'story': '雨夜林青推门走进便利店，与店员陈明相遇。',
                'durationSec': 30, 'mode': 'import_story',
            })
            assert response.status_code == 201, response.text
            pid = response.json()['project']['id']
            record = await repo.get(pid)
            assert record is not None
            version = record.project['version']
            record.project['script'] = {'title': '隔离测试', 'scenes': [], 'shots': [{
                'id': 'verify-shot', 'durationSec': 5, 'characterIds': [],
                'title': '入室', 'action': '推门进入', 'visualDescription': '林青推门进入便利店',
                'dialogue': '你终于来了。', 'resolution': '2K',
            }]}
            await repo.save(record)
            base = f'/api/projects/{pid}'
            preview = await client.post(base + '/shots/verify-shot/visual/preflight',
                                        json={'expectedVersion': version})
            assert preview.status_code == 200 and preview.json()['ready'], preview.text
            assert preview.json()['parameters']['resolution'] == '768P'
            request = {'expectedVersion': version, 'operationId': 'runtime-single-operation',
                       'preflightFingerprint': preview.json()['fingerprint']}
            response = await client.post(base + '/shots/verify-shot/video-jobs', json=request)
            assert response.status_code == 202, response.text
            jid = response.json()['id']
            repeated = await client.post(base + '/shots/verify-shot/video-jobs', json=request)
            assert repeated.json()['id'] == jid and FakeH3.submissions == 0
            assert await dispatcher.dispatch_once() == 1
            job = await wait_for(lambda: store.get(jid),
                lambda j: j and j.get('taskId') == 'fake-h3-task-1', 'Saved supplier ID')
            assert job['status'] == 'polling' and FakeH3.submissions == 1
            print('PASS: PostgreSQL/outbox -> Redis -> Worker, task ID persisted', flush=True)

            stop(worker, crash=True)
            stop(api)
            # Advance lease expiry only in this disposable test DB instead of waiting 900s.
            await store.change(jid, lambda row: row.update(leaseUntil=0))
            FakeH3.complete = True
            api = spawn('api-after', api_args)
            worker = spawn('worker-after', worker_args)
            await wait_for(lambda: client.get('/health'),
                           lambda r: r.status_code == 200, 'API restart')
            saved = await client.get(base + f'/video-jobs/{jid}')
            assert saved.json()['taskId'] == 'fake-h3-task-1' and saved.json()['canRecover']
            recovery = await client.post(base + f'/video-jobs/{jid}/recover', json={})
            assert recovery.status_code == 202, recovery.text
            assert await dispatcher.dispatch_once() == 1
            await wait_for(lambda: store.get(jid),
                lambda j: j and j['status'] == 'recoverable', 'Download failure recorded')
            assert FakeH3.submissions == 1 and FakeH3.downloads == 1
            print('PASS: API/Worker restart resumes task without resubmitting', flush=True)

            FakeH3.fail_download = False
            recovery = await client.post(base + f'/video-jobs/{jid}/recover', json={})
            assert recovery.status_code == 202, recovery.text
            assert await dispatcher.dispatch_once() == 1
            finished = await wait_for(lambda: store.get(jid),
                lambda j: j and j['status'] == 'succeeded', 'Final saved video')
            assert finished['callsStarted'] == {'text': 0, 'video': 1}
            asset = finished['result']['asset']
            assert not asset['valid'] and not asset.get('frameExtractionError'), asset
            adopted = await client.post(base + f'/video-jobs/{jid}/adopt')
            assert adopted.status_code == 200 and adopted.json()['result']['adopted'], adopted.text
            for key in ('objectKey', 'firstFrameObjectKey', 'lastFrameObjectKey'):
                s3.head_object(Bucket='comicflow-verify', Key=asset[key])
            access = await client.get(base + f"/video-resources/{asset['id']}/access")
            assert access.status_code == 200, access.text
            media = await client.get(access.json()['url'])
            assert media.content == (OUT / 'fake-h3.mp4').read_bytes()
            assert FakeH3.submissions == 1 and FakeH3.downloads == 2
            assert FakeH3.payload['resolution'] == '768P'
            assert FakeH3.payload['content'][0]['text'] == preview.json()['prompt']['text']
            print('PASS: download recovery, MinIO video/frames, playback bytes', flush=True)
            report = {'schema': schema, 'status': 'passed', 'realModelCalls': 0,
                      'fakeSubmissions': FakeH3.submissions, 'fakeQueries': FakeH3.queries,
                      'fakeDownloads': FakeH3.downloads, 'callsStarted': finished['callsStarted'],
                      'workerCrash': True, 'apiRestart': True, 'leaseExpiry': 'test-db-simulated',
                      'resolutionRequested': '768P', 'media': 'local FFmpeg test video',
                      'egress': 'Docker internal network', 'projectId': pid, 'jobId': jid}
            (OUT / 'runtime-report.json').write_text(json.dumps(report, indent=2) + '\n')
    finally:
        for proc in reversed(processes):
            stop(proc)
        for log in logs:
            log.close()
        await engine.dispose()


def main() -> None:
    configure()
    subprocess.run([sys.executable, '-m', 'alembic', '-c', str(ROOT / 'alembic.ini'),
                    'upgrade', 'head'], cwd=ROOT, check=True)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    'color=c=blue:s=360x640:r=24:d=5', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(OUT / 'fake-h3.mp4')], check=True)
    server = ThreadingHTTPServer(('127.0.0.1', 18093), FakeH3)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(verify())
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
