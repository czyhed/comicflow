"""Disposable PostgreSQL/Redis/Worker/MinIO verification; no external network."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from verify_video_runtime import configure

OUT = Path('/verification')
PREFIX = 'comicflow_verify_images'


class FakeImages(BaseHTTPRequestHandler):
    submissions = 0
    polls = 0
    downloads = 0
    complete = False
    fail_download = True
    image = b''
    board = b''
    source_image = None

    def log_message(self, *_args):
        pass

    def reply(self, data, status=200, mime='application/json'):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        cls = type(self)
        payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert payload['model'] in {'wan2.2-t2i-flash', 'wan2.6-image'}, payload
        if payload['model'] == 'wan2.6-image':
            assert payload['parameters']['n'] == 1
            assert payload['parameters']['size'] == '1536*1024'
            content = payload['input']['messages'][0]['content']
            cls.source_image = base64.b64decode(content[1]['image'].split(',')[1])
            assert cls.source_image == cls.image
            assert '严格侧面' in content[0]['text'] and '9:16' not in content[0]['text']
        cls.submissions += 1
        self.reply({'output': {'task_id': f'fake-image-{cls.submissions}'}})

    def do_GET(self):
        cls = type(self)
        if self.path.endswith(('/image.png', '/board.png')):
            assert not self.headers.get('Authorization')
            cls.downloads += 1
            self.reply(b'{}' if cls.fail_download else (cls.board if self.path.endswith('/board.png') else cls.image),
                       503 if cls.fail_download else 200, 'image/png')
        else:
            cls.polls += 1
            url = 'http://127.0.0.1:18095/' + ('board.png' if self.path.endswith('fake-image-2') else 'image.png')
            self.reply({'output': {'task_status': 'SUCCEEDED' if cls.complete else 'RUNNING',
                'results': [{'url': url}],
                'choices': [{'message': {'content': [{'image': url}]}}]}})


async def verify():
    import boto3
    import httpx
    from comicflow.infrastructure.database import SqlAlchemyProjectRepository, create_session_factory
    from comicflow.infrastructure.image_jobs import SqlImageJobStore
    from comicflow.worker.celery_app import publish_to_celery
    from comicflow.worker.outbox import OutboxDispatcher
    from redis import Redis
    from sqlalchemy import text

    assert Path.cwd() == OUT
    assert os.environ['DATABASE_URL'].endswith('@postgres/comicflow_verify')
    logs, processes = [], []

    def spawn(name, args):
        log = (OUT / f'image-{name}.log').open('w')
        logs.append(log)
        proc = subprocess.Popen([sys.executable, *args], stdout=log, stderr=log)
        processes.append(proc)
        return proc

    def stop(proc, crash=False):
        if proc.poll() is None:
            proc.kill() if crash else proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    async def wait_for(fetch, predicate):
        deadline = time.monotonic() + 40
        value = None
        while time.monotonic() < deadline:
            try:
                value = await fetch()
                if predicate(value):
                    return value
            except httpx.ConnectError:
                pass
            await asyncio.sleep(0.2)
        raise AssertionError(f'Wait failed: {value}')

    s3 = boto3.client('s3', endpoint_url=os.environ['S3_ENDPOINT'],
        aws_access_key_id='verification', aws_secret_access_key='verification-only',
        region_name='us-east-1')
    s3.create_bucket(Bucket='comicflow-verify')
    assert Redis.from_url(os.environ['REDIS_URL']).ping()
    engine, sessions = create_session_factory(os.environ['DATABASE_URL'])
    store = SqlImageJobStore(sessions)
    dispatcher = OutboxDispatcher(SqlAlchemyProjectRepository(sessions), publish_to_celery)
    api_args = ['-m', 'uvicorn', 'comicflow.api.app:app', '--host', '127.0.0.1', '--port', '18096']
    worker_args = ['-m', 'celery', '-A', 'comicflow.worker.celery_app:celery_app', 'worker',
                   '--pool=solo', '--concurrency=1', '--loglevel=INFO', '-Q', f'{PREFIX}.tasks',
                   '--without-gossip', '--without-mingle']
    try:
        async with engine.connect() as conn:
            schema = (await conn.execute(text('select version_num from alembic_version'))).scalar()
            assert schema == '0004_image_jobs'
        api = spawn('api-before', api_args)
        worker = spawn('worker-before', worker_args)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18096', timeout=10) as client:
            await wait_for(lambda: client.get('/health'), lambda r: r.status_code == 200)
            response = await client.post('/api/model-registry/connections', json={
                'revision': 0, 'name': 'local-fake', 'baseUrl': 'http://127.0.0.1:18095',
                'apiKey': 'fake-only'})
            assert response.status_code == 200, response.text
            view = response.json()
            response = await client.post('/api/model-registry/models', json={
                'revision': view['revision'], 'name': 'fake-image',
                'connectionId': view['connections'][0]['id'], 'protocol': 'wan-image',
                'model': 'wan2.2-t2i-flash', 'enabled': True,
                'config': {'timeoutMs': 30000}})
            assert response.status_code == 200, response.text
            view = response.json()
            response = await client.put('/api/model-registry/bindings', json={
                'revision': view['revision'], 'bindings': {'image': view['models'][0]['id']}})
            assert response.status_code == 200, response.text
            revision = response.json()['revision']
            response = await client.post('/api/projects', json={'inputType': 'story',
                'story': '雨夜林青推门走进便利店，与店员陈明相遇。', 'durationSec': 30, 'mode': 'import_story'})
            assert response.status_code == 201, response.text
            pid = response.json()['project']['id']
            base = f'/api/projects/{pid}'
            response = await client.post(base + '/characters', json={'name': '林青',
                'appearance': '短发', 'clothing': '蓝衣', 'personality': '沉静', 'voice': {'language': 'zh-CN'}})
            assert response.status_code == 200 or response.status_code == 201, response.text
            cid = response.json()['id']
            version = (await client.get(base)).json()['project']['version']
            payload = {'expectedVersion': version, 'operationId': 'one-click', 'purpose': 'candidate'}
            response = await client.post(base + f'/characters/{cid}/image-jobs', json=payload)
            assert response.status_code == 202, response.text
            jid = response.json()['id']
            repeat = await client.post(base + f'/characters/{cid}/image-jobs', json=payload)
            assert repeat.json()['id'] == jid and FakeImages.submissions == 0
            assert await dispatcher.dispatch_once() == 1
            saved = await wait_for(lambda: store.get(jid), lambda j: j and j.get('taskId'))
            assert saved['taskId'] == 'fake-image-1' and FakeImages.submissions == 1
            stop(worker, crash=True)
            stop(api)
            await store.change(jid, lambda j: j.update(leaseUntil=0))
            FakeImages.complete = True
            api = spawn('api-after', api_args)
            worker = spawn('worker-after', worker_args)
            await wait_for(lambda: client.get('/health'), lambda r: r.status_code == 200)
            # Switch current binding off; saved revision must still resolve the original adapter.
            changed = await client.put('/api/model-registry/bindings',
                                       json={'revision': revision, 'bindings': {}})
            assert changed.status_code == 200, changed.text
            response = await client.get(base + f'/image-jobs/{jid}')
            assert response.json()['canRecover'] and response.json()['taskId'] == 'fake-image-1'
            response = await client.post(base + f'/image-jobs/{jid}/recover')
            assert response.status_code == 202, response.text
            assert await dispatcher.dispatch_once() == 1
            await wait_for(lambda: store.get(jid), lambda j: j and j['status'] == 'recoverable')
            assert FakeImages.submissions == 1 and FakeImages.downloads == 1
            FakeImages.fail_download = False
            assert (await client.post(base + f'/image-jobs/{jid}/recover')).status_code == 202
            assert await dispatcher.dispatch_once() == 1
            done = await wait_for(lambda: store.get(jid), lambda j: j and j['status'] == 'succeeded')
            assert done['callsStarted'] == 1 and done['applied']
            card = (await client.get(base + '/characters')).json()[0]
            assert not card.get('referenceImageObjectKey')
            candidate = card['referenceImageCandidate']
            s3.head_object(Bucket='comicflow-verify', Key=candidate['objectKey'])
            assert (await client.get(candidate['url'])).content == FakeImages.image
            assert FakeImages.submissions == 1 and FakeImages.downloads == 2
            # Explicit main approval, then one edit request for the complete board.
            response = await client.post(base + f'/characters/{cid}/reference-candidate/approve',
                json={'candidateId': candidate['id'], 'expectedVersion': (await client.get(base)).json()['project']['version']})
            assert response.status_code == 200, response.text
            view = (await client.get('/api/model-registry')).json()
            response = await client.post('/api/model-registry/models', json={
                'revision': view['revision'], 'name': 'fake-board',
                'connectionId': view['connections'][0]['id'], 'protocol': 'wan26-image',
                'model': 'wan2.6-image', 'enabled': True,
                'config': {'timeoutMs': 30000, 'size': '1536*1024'}})
            assert response.status_code == 200, response.text
            view = response.json()
            model = next(m for m in view['models'] if m['name'] == 'fake-board')
            response = await client.put('/api/model-registry/bindings', json={
                'revision': view['revision'], 'bindings': {'image-edit': model['id']}})
            assert response.status_code == 200, response.text
            revision = response.json()['revision']
            FakeImages.complete = False
            version = (await client.get(base)).json()['project']['version']
            response = await client.post(base + f'/characters/{cid}/image-jobs', json={
                'expectedVersion': version, 'operationId': 'one-board', 'purpose': 'board'})
            assert response.status_code == 202, response.text
            board_jid = response.json()['id']
            assert await dispatcher.dispatch_once() == 1
            await wait_for(lambda: store.get(board_jid), lambda j: j and j.get('taskId'))
            stop(worker, crash=True)
            stop(api)
            await store.change(board_jid, lambda j: j.update(leaseUntil=0))
            FakeImages.complete = True
            api = spawn('api-board-after', api_args)
            worker = spawn('worker-board-after', worker_args)
            await wait_for(lambda: client.get('/health'), lambda r: r.status_code == 200)
            response = await client.put('/api/model-registry/bindings',
                                       json={'revision': revision, 'bindings': {}})
            assert response.status_code == 200, response.text
            assert (await client.post(base + f'/image-jobs/{board_jid}/recover')).status_code == 202
            assert await dispatcher.dispatch_once() == 1
            board_job = await wait_for(lambda: store.get(board_jid), lambda j: j and j['status'] == 'succeeded')
            assert board_job['callsStarted'] == 1 and FakeImages.submissions == 2
            card = (await client.get(base + '/characters')).json()[0]
            assert not card.get('referenceBoard')
            board = card['referenceBoardCandidate']
            assert (await client.get(board['url'])).content == FakeImages.board
            version = (await client.get(base)).json()['project']['version']
            response = await client.post(base + f'/characters/{cid}/reference-board/approve',
                json={'candidateId': board['id'], 'expectedVersion': version})
            assert response.status_code == 200, response.text
            assert response.json()['character']['referenceBoard']['status'] == 'approved'
            # Use production character selection + H3 reference planner, without video submission.
            from comicflow.api.app import create_configured_runtime
            from comicflow.providers.h3_skill import reference_plan
            runtime = create_configured_runtime()
            record = await runtime.pipeline._repository.get(pid)
            record.project['script'] = {'shots': [{'id': 's1', 'characterIds': [cid]}]}
            await runtime.pipeline._repository.save(record)
            characters = await runtime.pipeline._video_preparation().character_inputs(pid, 's1')
            plan = reference_plan({'durationSec': 5}, characters)
            assert len(plan['images']) == 1 and plan['images'][0]['id'] == cid
            assert plan['images'][0]['view'] == 'reference-board'
            assert board['objectKey'] in plan['images'][0]['url']
            report = {'status': 'passed', 'schema': schema, 'realModelCalls': 0,
                'fakeSubmissions': FakeImages.submissions, 'fakePolls': FakeImages.polls,
                'fakeDownloads': FakeImages.downloads, 'workerCrash': True, 'apiRestart': True,
                'configurationSwitched': True, 'candidateInstalled': True, 'boardCandidateAndApproval': True,
                'boardEditSubmissions': board_job['callsStarted'], 'h3ReferenceCount': len(plan['images']),
                'leaseExpiry': 'test-db-simulated', 'egress': 'Docker internal network'}
            (OUT / 'image-runtime-report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report), flush=True)
    finally:
        for proc in reversed(processes):
            stop(proc)
        for log in logs:
            log.close()
        await engine.dispose()


def main():
    from PIL import Image
    configure()
    os.environ['COMICFLOW_REDIS_NAMESPACE'] = PREFIX
    os.environ['USE_MINIMAX_H3'] = 'false'
    subprocess.run([sys.executable, '-m', 'alembic', '-c', '/workspace/alembic.ini',
                    'upgrade', 'head'], cwd='/workspace', check=True)
    image = io.BytesIO()
    Image.new('RGB', (256, 384), 'blue').save(image, 'PNG')
    FakeImages.image = image.getvalue()
    board = io.BytesIO()
    Image.new('RGB', (768, 512), 'navy').save(board, 'PNG')
    FakeImages.board = board.getvalue()
    server = ThreadingHTTPServer(('127.0.0.1', 18095), FakeImages)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asyncio.run(verify())
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
