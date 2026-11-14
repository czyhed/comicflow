"""Compose stored moving footage and original audio, without model requests."""

import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore


def _run(command: list[str]) -> bytes:
    try:
        return subprocess.run(command, check=True, capture_output=True, timeout=300).stdout
    except (subprocess.SubprocessError, OSError) as error:
        raise RuntimeError('COMPOSITION_MEDIA_INVALID') from error


def _encode(
    shots: list[JsonObject], durations: list[float], paths: list[Path],
    voices: list[Path | None], directory: Path, ffmpeg: str,
    starts: list[float],
) -> None:
    probe_name = 'ffprobe.exe' if Path(ffmpeg).suffix.lower() == '.exe' else 'ffprobe'
    ffprobe = (str(Path(ffmpeg).with_name(probe_name))
               if Path(ffmpeg).parent != Path('.') else probe_name)
    if shutil.which(ffmpeg) is None or shutil.which(ffprobe) is None:
        raise RuntimeError('FFMPEG_NOT_AVAILABLE')
    segments = []
    for index, (shot, seconds, path, voice, start) in enumerate(zip(
        shots, durations, paths, voices, starts, strict=True,
    )):
        is_video = path.suffix == '.mp4'
        metadata = json.loads(_run([
            ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(path),
        ]))
        streams = metadata.get('streams', [])
        if not any(item.get('codec_type') == 'video' for item in streams):
            raise RuntimeError('COMPOSITION_MEDIA_INVALID')
        has_audio = any(item.get('codec_type') == 'audio' for item in streams)
        if is_video:
            video_stream = next(item for item in streams if item.get('codec_type') == 'video')
            try:
                duration = float(video_stream['duration'])
            except (ValueError, KeyError, TypeError) as error:
                raise RuntimeError('COMPOSITION_MEDIA_INVALID') from error
            if duration + .05 < start + seconds:
                raise RuntimeError('COMPOSITION_VIDEO_TOO_SHORT')
        args = [ffmpeg, '-v', 'error', '-y']
        if not is_video:
            args += ['-loop', '1', '-t', str(seconds)]
        args += ['-i', str(path)]
        if voice is not None:
            args += ['-i', str(voice)]
            audio_input = '1:a:0'
        elif has_audio:
            audio_input = '0:a:0'
        else:
            if str(shot.get('dialogue') or shot.get('narration') or '').strip():
                raise RuntimeError('COMPOSITION_AUDIO_MISSING')
            args += ['-f', 'lavfi', '-i', f'anullsrc=r=48000:cl=stereo:d={seconds}']
            audio_input = '1:a:0'
        audio_start = start if voice is not None or has_audio else 0
        output = directory / f'segment-{index}.mp4'
        args += [
            '-map', '0:v:0', '-map', audio_input,
            '-vf', f'trim=start={start}:duration={seconds},setpts=PTS-STARTPTS,'
            'scale=1080:1920:force_original_aspect_ratio=decrease,'
            'pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
            '-af', f'aresample=48000,atrim=start={audio_start}:duration={seconds},'
            f'asetpts=PTS-STARTPTS,apad,atrim=duration={seconds}',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-threads', '2',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
            '-b:a', '192k', '-t', str(seconds), '-movflags', '+faststart', str(output),
        ]
        _run(args)
        segments.append(output)
    listing = directory / 'concat.txt'
    listing.write_text(''.join(f"file '{item.name}'\n" for item in segments), encoding='utf-8')
    out = directory / 'video.mp4'
    _run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', str(listing),
          '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'aac',
          '-t', str(sum(durations)), '-movflags', '+faststart', str(out)])
    _run([ffmpeg, '-v', 'error', '-y', '-i', str(out), '-frames:v', '1',
          str(directory / 'cover.jpg')])


async def compose_video_assets(
    project: JsonObject, shots: list[JsonObject], durations: list[float], subtitles: bytes,
    store: AssetStore | None, ffmpeg: str,
) -> JsonObject:
    if store is None:
        raise RuntimeError('COMPOSITION_MEDIA_UNREADABLE')
    visuals = {str(item.get('shotId')): item for item in project.get('visualAssets', [])
               if isinstance(item, dict) and item.get('valid')}
    audio = {str(item.get('shotId')): item for item in project.get('audioAssets', [])
             if isinstance(item, dict) and item.get('valid')}
    with tempfile.TemporaryDirectory(prefix='comicflow-video-export-') as directory:
        root = Path(directory)
        paths: list[Path] = []
        voices: list[Path | None] = []
        for index, shot in enumerate(shots):
            visual = visuals.get(str(shot['id']), {})
            key = visual.get('objectKey')
            if not isinstance(key, str) or not key:
                raise RuntimeError('COMPOSITION_MEDIA_UNREADABLE')
            voice = audio.get(str(shot['id']))
            # H3's current video owns its soundtrack. Legacy TTS/extracted assets
            # must not replace it or make direct composition depend on a WAV copy.
            if visual.get('provider') == 'minimax' and visual.get('mediaType') == 'video':
                voice = None
            if voice and voice.get('source') == 'video-native' and (
                voice.get('sourceVisualAssetId') != visual.get('id')
            ):
                raise RuntimeError('COMPOSITION_AUDIO_STALE')
            path = root / f'input-{index}{".mp4" if visual.get("mediaType") == "video" else ".png"}'
            voice_path = None
            try:
                path.write_bytes(await store.get_bytes(key, max_bytes=200 * 1024 * 1024))
                if voice:
                    voice_path = root / f'voice-{index}.wav'
                    voice_path.write_bytes(await store.get_bytes(voice['objectKey']))
            except Exception as error:
                raise RuntimeError('COMPOSITION_MEDIA_UNREADABLE') from error
            paths.append(path)
            voices.append(voice_path)
        starts = [float(project.get('compositionTrims', {}).get(shot['id'], {}).get('inSec', 0))
                  for shot in shots]
        await asyncio.to_thread(_encode, shots, durations, paths, voices, root, ffmpeg, starts)
        (root / 'subtitles.srt').write_bytes(subtitles)
        files = ['video.mp4', 'cover.jpg', 'subtitles.srt']
        return {
            'files': files, 'format': 'h264-aac-1080x1920-30fps',
            'projectId': project['id'], 'durationMs': round(sum(durations) * 1000),
            'artifacts': {name: (root / name).read_bytes() for name in files},
        }
