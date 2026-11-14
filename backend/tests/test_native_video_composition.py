import asyncio
import inspect
import json
import socket
import subprocess
from array import array

import httpx
import pytest
from comicflow.api.app import create_app
from comicflow.domain.errors import DomainError
from comicflow.domain.models import CreateProject
from comicflow.infrastructure.memory import create_memory_runtime
from comicflow.providers.audio import TtsHttpProvider
from comicflow.providers.ffmpeg import FfmpegCompositionProvider
from comicflow.providers.mock_media import MockDynamicVisualProvider


class LocalStore:
    def __init__(self, objects):
        self.objects = objects

    async def get_bytes(self, key, max_bytes=20 * 1024 * 1024):
        return self.objects[key]

    async def put_bytes(self, object_key, content, content_type):
        self.objects[object_key] = content
        return object_key

    async def presigned_get_url(self, key, **kwargs):
        return f'https://offline.invalid/{key}'

    async def exists(self, key):
        return key in self.objects


@pytest.fixture(autouse=True)
async def no_model_network(monkeypatch):
    original_connect = socket.socket.connect
    def deny(sock, address):
        # Windows asyncio's internal socketpair uses a loopback connection.
        if any(frame.function == '_fallback_socketpair' and frame.filename == socket.__file__
               for frame in inspect.stack()):
            return original_connect(sock, address)
        pytest.fail('No real sockets allowed')
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)


@pytest.fixture(scope='module')
def clips(tmp_path_factory):
    root = tmp_path_factory.mktemp('native-media')
    result = {}
    for i, audio in enumerate([True, True, False]):
        path = root / f'{i}.mp4'
        args = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                f'testsrc2=size={96 + i * 16}x160:rate={12 + i}:duration=1.2']
        if audio:
            args += ['-f', 'lavfi', '-i', f'sine=frequency={440 + i*220}:duration=1.2',
                     '-c:a', 'aac']
        args += ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)]
        subprocess.run(args, check=True, capture_output=True)
        result[str(i)] = path.read_bytes()
    return result


async def prepared(clips):
    runtime = create_memory_runtime()
    created = await runtime.pipeline.create_project(CreateProject(
        input_type='story', story='夜幕降临，两个人在街道上相遇交谈。',
        mode='import_story', duration_sec=30,
    ))
    pid = created['project']['id']
    record = await runtime.pipeline._repository.get(pid)
    record.project['script'] = {'scenes': [], 'shots': [{
        'id': 's1', 'durationSec': 1, 'narration': '夜幕降临。',
    }]}
    record.project['visualAssets'] = [{
        'id': 'v1', 'shotId': 's1', 'provider': 'minimax', 'mediaType': 'video',
        'objectKey': '0', 'valid': True,
    }]
    await runtime.pipeline._repository.save(record)
    runtime.pipeline._asset_store = LocalStore(dict(clips))

    class Forbidden:
        async def generate(self, *args):
            raise AssertionError('Native H3 audio must not call TTS/lip sync')
    runtime.pipeline._tts_provider = Forbidden()
    runtime.pipeline._lip_sync_provider = Forbidden()
    return runtime, pid, record.project['version']


async def test_native_audio_is_extracted_and_reused_without_models(clips):
    runtime, pid, version = await prepared(clips)
    first = await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    assert first['asset']['source'] == 'video-native'
    assert first['asset']['sourceVisualAssetId'] == 'v1'
    assert first['asset']['durationMs'] > 1000
    assert first['lipSync'] is None
    assert first['timeline']['durationMs'] == 1000
    second = await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    assert second['asset']['id'] == first['asset']['id']
    record = await runtime.pipeline._repository.get(pid)
    assert len(record.project['audioAssets']) == 1
    assert runtime.pipeline._composition_readiness(record.project)['missingAudioShotIds'] == []


async def test_native_video_can_queue_and_compose_without_separate_audio(clips):
    runtime, pid, version = await prepared(clips)
    runtime.pipeline._composition_provider = FfmpegCompositionProvider(
        asset_store=runtime.pipeline._asset_store,
    )
    job = await runtime.pipeline.request_composition(
        pid, expected_version=version, idempotency_key='native-direct',
    )
    repeated = await runtime.pipeline.request_composition(
        pid, expected_version=version, idempotency_key='native-direct',
    )
    assert repeated['id'] == job['id']
    assert not (await runtime.pipeline._repository.get(pid)).project.get('audioAssets')
    completed = await runtime.pipeline.run_job(job['id'])
    assert completed['status'] == 'succeeded'
    project = (await runtime.pipeline._repository.get(pid)).project
    assert project['exportManifest']['files'] == ['video.mp4', 'cover.jpg', 'subtitles.srt']
    assert not project.get('audioAssets')  # No hidden WAV preparation or model calls.


async def test_direct_composition_missing_native_audio_fails_without_paid_fallback(clips):
    runtime, pid, version = await prepared(clips)
    record = await runtime.pipeline._repository.get(pid)
    record.project['visualAssets'][0]['objectKey'] = '2'
    await runtime.pipeline._repository.save(record)
    runtime.pipeline._composition_provider = FfmpegCompositionProvider(
        asset_store=runtime.pipeline._asset_store,
    )
    job = await runtime.pipeline.request_composition(pid, expected_version=version)
    completed = await runtime.pipeline.run_job(job['id'])
    assert completed['status'] == 'failed'
    assert completed['error'] == 'COMPOSITION_AUDIO_MISSING'
    project = (await runtime.pipeline._repository.get(pid)).project
    assert not project.get('audioAssets')
    assert project['visualAssets'][0]['valid']
    assert not project.get('exportManifest')


async def test_selected_video_encodes_real_trial_without_unfinished_shots(clips, tmp_path):
    runtime, pid, version = await prepared(clips)
    record = await runtime.pipeline._repository.get(pid)
    record.project['script']['shots'].append({'id': 'unfinished', 'durationSec': 10})
    old = {'files': ['original.mp4']}
    record.project['exportManifest'] = old
    await runtime.pipeline._repository.save(record)
    store = runtime.pipeline._asset_store
    runtime.pipeline._composition_provider = FfmpegCompositionProvider(asset_store=store)
    job = await runtime.pipeline.request_composition(pid, expected_version=version, shot_ids=['s1'])
    completed = await runtime.pipeline.run_job(job['id'])
    assert completed['status'] == 'succeeded'
    manifest = await runtime.pipeline.get_export_manifest(pid, job_id=job['id'])
    assert manifest['durationMs'] == 1000 and manifest['shotIds'] == ['s1']
    output = tmp_path / 'trial.mp4'
    output.write_bytes(store.objects[manifest['objectKeys']['video.mp4']])
    metadata = json.loads((await asyncio.to_thread(subprocess.run,
        ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(output)],
        check=True, capture_output=True,
    )).stdout)
    assert {s['codec_type'] for s in metadata['streams']} == {'video', 'audio'}
    video = next(s for s in metadata['streams'] if s['codec_type'] == 'video')
    assert float(video['duration']) == pytest.approx(1, abs=.05)
    assert (await runtime.pipeline._repository.get(pid)).project['exportManifest'] == old


async def test_trim_removes_opening_picture_and_audio_and_shifts_subtitles(clips, tmp_path):
    source = tmp_path / 'two-states.mp4'
    await asyncio.to_thread(subprocess.run, [
        'ffmpeg', '-v', 'error', '-y',
        '-f', 'lavfi', '-i', 'color=c=red:s=96x160:r=30:d=0.6',
        '-f', 'lavfi', '-i', 'color=c=blue:s=96x160:r=30:d=0.6',
        '-f', 'lavfi', '-i', 'sine=frequency=220:duration=0.6',
        '-f', 'lavfi', '-i', 'sine=frequency=880:duration=0.6',
        '-filter_complex', '[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]',
        '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', str(source),
    ], check=True, capture_output=True)
    runtime, pid, version = await prepared({**clips, '0': source.read_bytes()})
    store = runtime.pipeline._asset_store
    record = await runtime.pipeline._repository.get(pid)
    record.project['script']['shots'].append({'id': 's2', 'durationSec': 1, 'narration': '继续。'})
    record.project['visualAssets'].append({
        'id': 'v2', 'shotId': 's2', 'provider': 'minimax', 'mediaType': 'video',
        'objectKey': '1', 'valid': True,
    })
    await runtime.pipeline._repository.save(record)
    runtime.pipeline._composition_provider = FfmpegCompositionProvider(asset_store=store)
    original = store.objects['0']
    job = await runtime.pipeline.request_composition(
        pid, expected_version=version, shot_ids=['s1', 's2'],
        shot_trims={'s1': {'inSec': .6, 'outSec': 1.2}},
    )
    done = await runtime.pipeline.run_job(job['id'])
    assert done['status'] == 'succeeded', done
    manifest = done['exportManifest']
    assert manifest['durationMs'] == 1600
    output = tmp_path / 'trimmed.mp4'
    output.write_bytes(store.objects[manifest['objectKeys']['video.mp4']])
    frame = (await asyncio.to_thread(subprocess.run, [
        'ffmpeg', '-v', 'error', '-ss', '0.1', '-i', str(output), '-frames:v', '1',
        '-vf', 'scale=2:2', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-',
    ], check=True, capture_output=True)).stdout
    assert frame[2] > frame[0] + 100  # Blue retained; the red opening was cut.
    pcm = (await asyncio.to_thread(subprocess.run, [
        'ffmpeg', '-v', 'error', '-i', str(output), '-t', '0.5', '-vn',
        '-ar', '8000', '-ac', '1', '-f', 's16le', '-',
    ], check=True, capture_output=True)).stdout
    samples = array('h', pcm)[800:3200]
    crossings = sum(a < 0 <= b for a, b in zip(samples, samples[1:], strict=False))
    assert crossings / (len(samples) / 8000) == pytest.approx(880, abs=30)
    srt = store.objects[manifest['objectKeys']['subtitles.srt']].decode()
    assert '00:00:00,600 --> 00:00:01,600' in srt
    assert store.objects['0'] == original


async def test_trim_beyond_actual_clip_fails_and_keeps_source(clips):
    runtime, pid, version = await prepared(clips)
    store = runtime.pipeline._asset_store
    runtime.pipeline._composition_provider = FfmpegCompositionProvider(asset_store=store)
    job = await runtime.pipeline.request_composition(
        pid, expected_version=version, shot_ids=['s1'],
        shot_trims={'s1': {'inSec': .5, 'outSec': 2}},
    )
    done = await runtime.pipeline.run_job(job['id'])
    assert done['status'] == 'failed' and done['error'] == 'COMPOSITION_VIDEO_TOO_SHORT'
    assert store.objects['0'] == clips['0']


async def test_automatic_native_video_skips_separate_audio_preparation(clips):
    runtime, pid, _version = await prepared(clips)
    record = await runtime.pipeline._repository.get(pid)
    record.project['input']['mode'] = 'automatic'
    record.project['stage'] = 'visual-completed'
    record.project['generationSession'] = {'mode': 'automatic', 'status': 'ready'}
    await runtime.pipeline._repository.save(record)
    result = await runtime.pipeline.advance_generation_session(pid)
    assert result['stage'] == 'audio-completed'
    project = (await runtime.pipeline._repository.get(pid)).project
    assert not project.get('audioAssets')


def test_subtitle_draft_preserves_both_dialogue_and_narration():
    from comicflow.providers.ffmpeg import _build_srt

    draft = _build_srt([{'dialogue': '女主：明天见。', 'narration': '列车驶入雨幕。'}], [15])
    assert '女主：明天见。' in draft
    assert '列车驶入雨幕。' in draft
    assert draft.count('-->') == 1  # A shot-level draft, not fabricated speech timing.


async def test_missing_native_track_does_not_fall_back_to_tts(clips):
    runtime, pid, version = await prepared(clips)
    record = await runtime.pipeline._repository.get(pid)
    record.project['visualAssets'][0]['objectKey'] = '2'
    await runtime.pipeline._repository.save(record)
    with pytest.raises(DomainError, match='VIDEO_AUDIO_MISSING'):
        await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    assert not (await runtime.pipeline._repository.get(pid)).project.get('audioAssets')


async def test_native_ambient_audio_with_no_spoken_lines(clips):
    runtime, pid, version = await prepared(clips)
    record = await runtime.pipeline._repository.get(pid)
    record.project['script']['shots'][0]['narration'] = ''
    await runtime.pipeline._repository.save(record)
    result = await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    assert result['asset']['source'] == 'video-native'
    assert result['timeline']['dialogue'] == []
    assert result['timeline']['durationMs'] == 1000


async def test_new_visual_invalidates_native_audio(clips, monkeypatch):
    runtime, pid, version = await prepared(clips)
    await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    class Replacement(MockDynamicVisualProvider):
        async def generate(self, shot, characters):
            return {'id': 'v2', 'shotId': shot['id'], 'objectKey': '1',
                    'provider': 'minimax', 'mediaType': 'video'}
    runtime.pipeline._dynamic_visual_provider = Replacement()
    candidate = await runtime.pipeline.generate_shot_visual(pid, 's1', expected_version=version)
    record = await runtime.pipeline._repository.get(pid)
    assert any(a['valid'] for a in record.project['audioAssets'])
    assert 's1' in record.project['timelines']
    await runtime.pipeline.adopt_video_job(pid, candidate['jobId'])
    record = await runtime.pipeline._repository.get(pid)
    assert not any(a['valid'] for a in record.project['audioAssets'])
    assert 's1' not in record.project['timelines']
    result = await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    assert result['asset']['sourceVisualAssetId'] == 'v2'


async def test_changed_project_during_extraction_is_not_overwritten(clips, monkeypatch):
    from comicflow.providers import native_audio
    runtime, pid, version = await prepared(clips)
    async def delayed(store, visual):
        record = await runtime.pipeline._repository.get(pid)
        record.project['version'] += 1
        record.project['title'] = 'concurrent edit'
        await runtime.pipeline._repository.save(record)
        return {'id': 'unused', 'durationMs': 1000}
    monkeypatch.setattr(native_audio, 'extract_native_audio', delayed)
    with pytest.raises(DomainError, match='VERSION_CONFLICT'):
        await runtime.pipeline.generate_shot_audio(pid, 's1', expected_version=version)
    record = await runtime.pipeline._repository.get(pid)
    assert record.project['title'] == 'concurrent edit'
    assert not record.project.get('audioAssets')


async def test_tts_401_is_not_an_unhandled_500(clips):
    runtime, pid, version = await prepared(clips)
    record = await runtime.pipeline._repository.get(pid)
    record.project['visualAssets'][0]['provider'] = 'other'
    await runtime.pipeline._repository.save(record)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(401, json={'message': 'private-secret'})
    runtime.pipeline._tts_provider = TtsHttpProvider(
        api_key='private-secret', transport=httpx.MockTransport(respond),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(runtime)),
                                 base_url='http://test') as client:
        response = await client.post(f'/api/projects/{pid}/shots/s1/audio',
                                     json={'expectedVersion': version})
    assert response.status_code == 401
    assert response.json()['error'] == 'PROVIDER_AUTH_FAILED'
    assert response.json()['stage'] == 'tts'
    assert len(calls) == 1
    assert 'private-secret' not in response.text


async def test_real_video_composition_keeps_motion_audio_and_planned_duration(clips, tmp_path):
    provider = FfmpegCompositionProvider(asset_store=LocalStore(clips))
    project = {'id': 'offline', 'script': {'shots': [
        {'id': str(i), 'durationSec': 1, 'narration': '夜幕降临。'} for i in range(2)
    ]}, 'visualAssets': [
        {'shotId': str(i), 'objectKey': str(i), 'provider': 'minimax',
         'mediaType': 'video', 'valid': True}
        for i in range(2)
    ], 'audioAssets': [
        # Old TTS or stale extracted files must never replace the current H3 soundtrack.
        {'shotId': '0', 'valid': True, 'objectKey': 'old-tts-must-not-be-read'},
        {'shotId': '1', 'valid': True, 'source': 'video-native',
         'sourceVisualAssetId': 'old-video', 'objectKey': 'old-wav-must-not-be-read'},
    ]}
    result = await provider.compose(project)
    path = tmp_path / 'out.mp4'
    path.write_bytes(result['artifacts']['video.mp4'])
    probe = await asyncio.to_thread(subprocess.run,
                            ['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                            '-of', 'json', str(path)], capture_output=True, check=True)
    body = json.loads(probe.stdout)
    assert {s['codec_type'] for s in body['streams']} == {'video', 'audio'}
    assert abs(float(body['format']['duration']) - 2) < .1
    frames = []
    for offset in [.1, .7, 1.5]:
        frame = await asyncio.to_thread(subprocess.run,
                                ['ffmpeg', '-v', 'error', '-ss', str(offset), '-i', str(path),
                                '-frames:v', '1', '-vf', 'scale=48:80', '-pix_fmt', 'rgb24',
                                '-f', 'rawvideo', '-'],
                               capture_output=True, check=True)
        frames.append(frame.stdout)
    assert sum(abs(a - b) for a, b in zip(frames[0], frames[1], strict=True)) / len(frames[0]) > 2
    audio_result = await asyncio.to_thread(subprocess.run,
                            ['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ar', '8000',
                            '-ac', '1', '-f', 's16le', '-'],
                           capture_output=True, check=True)
    audio = audio_result.stdout
    assert any(audio) and len(audio) > 1000
    samples = array('h', audio)
    for start, expected in [(2000, 440), (10000, 660)]:
        window = samples[start:start + 4000]
        crossings = sum(a < 0 <= b for a, b in zip(window, window[1:], strict=False))
        assert abs(crossings * 2 - expected) < 30
    assert result['artifacts']['cover.jpg'].startswith(b'\xff\xd8')
    assert '夜幕降临' in result['artifacts']['subtitles.srt'].decode()


async def test_broken_video_refuses_instead_of_rendering_text_cards():
    provider = FfmpegCompositionProvider(asset_store=LocalStore({'bad': b'not-video'}))
    with pytest.raises(RuntimeError, match='COMPOSITION_MEDIA_INVALID'):
        await provider.compose({'id': 'offline', 'script': {'shots': [
            {'id': 's1', 'durationSec': 1},
        ]}, 'visualAssets': [{
            'shotId': 's1', 'objectKey': 'bad', 'mediaType': 'video', 'valid': True,
        }]})
