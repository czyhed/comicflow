"""Extract an existing video's original audio locally; never call a model."""

import asyncio
import json
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from uuid import uuid4

from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore


def _extract(content: bytes) -> tuple[bytes, int, int]:
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('FFMPEG_NOT_AVAILABLE')
    with tempfile.TemporaryDirectory(prefix='comicflow-native-audio-') as directory:
        source, output = Path(directory) / 'video.mp4', Path(directory) / 'audio.wav'
        source.write_bytes(content)
        try:
            probe = subprocess.run([
                'ffprobe', '-v', 'error', '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_type', '-of', 'json', str(source),
            ], check=True, capture_output=True, timeout=30)
            if not json.loads(probe.stdout).get('streams'):
                raise RuntimeError('VIDEO_AUDIO_MISSING')
            subprocess.run([
                'ffmpeg', '-v', 'error', '-y', '-i', str(source), '-map', '0:a:0', '-vn',
                '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', str(output),
            ], check=True, capture_output=True, timeout=60)
            with wave.open(str(output), 'rb') as audio:
                rate = audio.getframerate()
                duration = round(audio.getnframes() * 1000 / rate)
            if duration <= 0:
                raise RuntimeError('VIDEO_AUDIO_INVALID')
            return output.read_bytes(), duration, rate
        except (subprocess.SubprocessError, ValueError, OSError, wave.Error) as error:
            raise RuntimeError('VIDEO_AUDIO_INVALID') from error


async def extract_native_audio(store: AssetStore | None, visual: JsonObject) -> JsonObject:
    key = visual.get('objectKey')
    if store is None or not isinstance(key, str) or not key:
        raise RuntimeError('VIDEO_AUDIO_UNREADABLE')
    try:
        content = await store.get_bytes(key, max_bytes=200 * 1024 * 1024)
    except Exception as error:
        raise RuntimeError('VIDEO_AUDIO_UNREADABLE') from error
    wav, duration, rate = await asyncio.to_thread(_extract, content)
    asset_id = f'audio-native-{uuid4().hex}'
    object_key = f'audio/native/{asset_id}.wav'
    try:
        await store.put_bytes(object_key, wav, 'audio/wav')
    except Exception as error:
        raise RuntimeError('VIDEO_AUDIO_STORE_FAILED') from error
    return {
        'id': asset_id, 'shotId': visual['shotId'], 'objectKey': object_key,
        'source': 'video-native', 'sourceVisualAssetId': visual['id'],
        'provider': 'local', 'durationMs': duration, 'sampleRate': rate,
        'sizeBytes': len(wav), 'valid': True,
    }
