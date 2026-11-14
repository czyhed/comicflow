from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from comicflow.domain.models import JsonObject

_BG = (20, 23, 28)
_ACCENT = (114, 239, 137)
_DIM = (168, 176, 186)
_WHITE = (245, 245, 245)
_CARD_W = 1080
_CARD_H = 1920
_FONT_CANDIDATES = (
    # Debian/Ubuntu fonts-noto-cjk
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)


class FfmpegCompositionProvider:
    """Compose stored moving footage with audio using local FFmpeg.

    Projects containing video use the strict media compositor. The legacy
    image/text-card renderer remains for projects without video (including Mock).
    """

    def __init__(
        self, *, ffmpeg_path: str = "ffmpeg", asset_store: Any | None = None
    ) -> None:
        self._ffmpeg_path = ffmpeg_path
        self._asset_store = asset_store

    async def compose(self, project: JsonObject) -> JsonObject:
        if any(item.get('valid') and item.get('mediaType') == 'video'
               for item in project.get('visualAssets', []) if isinstance(item, dict)):
            from comicflow.providers.video_composition import compose_video_assets

            shots = self._shots(project)
            durations = [self._shot_duration(shot) for shot in shots]
            trims = project.get('compositionTrims', {})
            durations = [float(trims[shot['id']]['outSec'] - trims[shot['id']]['inSec'])
                         if shot['id'] in trims else duration
                         for shot, duration in zip(shots, durations, strict=True)]
            if not shots or sum(durations) <= 0:
                raise RuntimeError('EXPORT_DURATION_INVALID')
            return await compose_video_assets(
                project, shots, durations, _build_srt(shots, durations).encode('utf-8'),
                self._asset_store, self._ffmpeg_path,
            )
        return await asyncio.to_thread(self._compose, project)

    def _compose(self, project: JsonObject) -> JsonObject:
        if shutil.which(self._ffmpeg_path) is None:
            raise RuntimeError("FFMPEG_NOT_AVAILABLE")
        shots = self._shots(project)
        if not shots:
            raise RuntimeError("EXPORT_DURATION_INVALID")
        font_path = _find_cjk_font()
        if font_path is None:
            raise RuntimeError("FFMPEG_COMPOSITION_FAILED")

        durations = [self._shot_duration(shot) for shot in shots]
        total_seconds = sum(durations)
        if total_seconds <= 0:
            raise RuntimeError("EXPORT_DURATION_INVALID")

        with tempfile.TemporaryDirectory(prefix="comicflow-export-") as directory:
            output_dir = Path(directory)
            video_path = output_dir / "video.mp4"
            cover_path = output_dir / "cover.jpg"
            subtitle_path = output_dir / "subtitles.srt"
            audio_segments = self._prepare_audio(project, shots, output_dir)
            visual_paths = self._prepare_visual(project, shots, output_dir)
            card_paths: list[Path] = []
            for index, shot in enumerate(shots):
                scene_title = ""
                for scene_item in project.get("script", {}).get("scenes", []):
                    if shot.get("id") in scene_item.get("shotIds", []):
                        scene_title = str(scene_item.get("title", ""))
                        break
                card = output_dir / f"card-{index:02d}.png"
                background = visual_paths[index] if visual_paths else None
                _render_card(
                    card, font_path, index, len(shots), scene_title, shot,
                    total_seconds, background,
                )
                card_paths.append(card)
            if audio_segments is not None:
                self._encode_with_audio(card_paths, durations, audio_segments, video_path)
            else:
                self._encode_cards(card_paths, durations, total_seconds, video_path)
            cover = Image.open(card_paths[0]).convert("RGB")
            cover.save(cover_path, "JPEG", quality=90)
            subtitle_path.write_bytes(_build_srt(shots, durations).encode("utf-8"))

            files = ["video.mp4", "cover.jpg", "subtitles.srt"]
            return {
                "files": files,
                "format": "h264-aac-1080x1920-30fps",
                "projectId": project["id"],
                "durationMs": round(total_seconds * 1000),
                "artifacts": {name: (output_dir / name).read_bytes() for name in files},
            }

    def _encode_cards(
        self, cards: list[Path], durations: list[float], total: float, out: Path
    ) -> None:
        """Encode visual assets (images or videos) with placeholder audio.

        Supports both static images and video files. Videos are concatenated directly,
        images are looped for their duration.
        """
        args: list[str] = [
            "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={total}",
        ]

        # Add inputs: videos or looped images
        for card, seconds in zip(cards, durations, strict=True):
            if card.suffix.lower() in ('.mp4', '.mov', '.avi', '.mkv'):
                # Video file: use directly
                args += ["-i", str(card)]
            else:
                # Image file: loop for duration
                args += ["-loop", "1", "-t", str(seconds), "-i", str(card)]

        concat_inputs = "".join(f"[{i}:v]" for i in range(1, len(cards) + 1))
        filter_complex = (
            f"[0:a]volume=0.07[a];"
            f"{concat_inputs}concat=n={len(cards)}:v=1:a=0[vc]"
        )
        args += [
            "-filter_complex", filter_complex,
            "-map", "[vc]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-r", "30", "-c:a", "aac", "-b:a", "96k",
            "-t", str(total), "-movflags", "+faststart", str(out),
        ]
        try:
            subprocess.run([self._ffmpeg_path, *args], check=True, capture_output=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError("FFMPEG_COMPOSITION_FAILED") from error

    def _prepare_audio(
        self, project: JsonObject, shots: list[JsonObject], output_dir: Path
    ) -> list[Path | None] | None:
        """Download per-shot voice assets (objectKey) as wav files aligned to shots.

        Returns None when no usable voices exist (callers keep the placeholder
        tone), otherwise one file path per shot with None for silent shots.
        """
        if self._asset_store is None:
            return None
        assets = project.get("audioAssets", [])
        keys: dict[str, str] = {}
        for asset in assets:
            if isinstance(asset, dict) and asset.get("valid") is not False:
                shot_id = asset.get("shotId")
                object_key = asset.get("objectKey")
                if isinstance(shot_id, str) and isinstance(object_key, str):
                    keys[shot_id] = object_key
        if not keys:
            return None
        import httpx
        result: list[Path | None] = []
        for shot in shots:
            shot_id = str(shot.get("id", ""))
            object_key = keys.get(shot_id)
            if not object_key:
                result.append(None)
                continue
            try:
                url = asyncio.run(
                    self._asset_store.presigned_get_url(object_key, rewrite_public=False)
                )
                response = httpx.get(url, timeout=60.0)
                response.raise_for_status()
                target = output_dir / f"voice-{shot_id}.wav"
                target.write_bytes(response.content)
                result.append(target)
            except Exception:  # noqa: BLE001
                result.append(None)
        if not any(result):
            return None
        return result

    def _prepare_visual(
        self, project: JsonObject, shots: list[JsonObject], output_dir: Path
    ) -> list[Path | None] | None:
        """Download generated visual assets (images or videos) aligned to shots.

        Video assets take priority over image assets. If a shot has a valid video,
        it will be used; otherwise, fall back to image keyframes.
        """
        if self._asset_store is None:
            return None
        assets = project.get("visualAssets", [])

        # Build a map of shot_id -> asset, prioritizing video over image
        shot_assets: dict[str, JsonObject] = {}
        for asset in assets:
            if not isinstance(asset, dict) or asset.get("valid") is False:
                continue
            shot_id = asset.get("shotId")
            object_key = asset.get("objectKey")
            media_type = asset.get("mediaType")

            if not isinstance(shot_id, str) or not isinstance(object_key, str):
                continue

            # Prioritize video over image
            if shot_id in shot_assets:
                existing_type = shot_assets[shot_id].get("mediaType")
                # If current asset is video and existing is not, replace
                if media_type == "video" and existing_type != "video":
                    shot_assets[shot_id] = asset
                # If both are videos or both are images, keep the first valid one
            else:
                shot_assets[shot_id] = asset

        if not shot_assets:
            return None

        import httpx
        result: list[Path | None] = []
        for shot in shots:
            shot_id = str(shot.get("id", ""))
            asset = shot_assets.get(shot_id)

            if not asset:
                result.append(None)
                continue

            object_key = asset.get("objectKey")
            media_type = asset.get("mediaType")

            try:
                url = asyncio.run(
                    self._asset_store.presigned_get_url(object_key, rewrite_public=False)
                )
                response = httpx.get(url, timeout=120.0)  # Increased timeout for videos
                response.raise_for_status()

                # Use appropriate file extension based on media type
                if media_type == "video":
                    target = output_dir / f"visual-{shot_id}.mp4"
                else:
                    target = output_dir / f"visual-{shot_id}.png"

                target.write_bytes(response.content)
                result.append(target)
            except Exception:  # noqa: BLE001
                result.append(None)

        if not any(result):
            return None
        return result

    def _encode_with_audio(
        self,
        cards: list[Path],
        durations: list[float],
        audio_segments: list[Path | None],
        out: Path,
    ) -> None:
        """Encode visual assets (images or videos) with audio tracks.

        Supports both static images and video files.
        """
        count = len(cards)
        args: list[str] = ["-hide_banner", "-loglevel", "error", "-y"]

        # Add video inputs: videos or looped images
        for card, seconds in zip(cards, durations, strict=True):
            if card.suffix.lower() in ('.mp4', '.mov', '.avi', '.mkv'):
                # Video file: use directly
                args += ["-i", str(card)]
            else:
                # Image file: loop for duration
                args += ["-loop", "1", "-t", str(seconds), "-i", str(card)]

        # One audio input per shot: the voice clip, or generator silence.
        silence_inputs: list[int] = []
        for index, segment in enumerate(audio_segments):
            if segment is not None:
                args += ["-i", str(segment)]
            else:
                args += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono:d={durations[index]}"]
                silence_inputs.append(index + count)

        if count == 0:
            return

        video_inputs = "".join(f"[{i}:v]" for i in range(count))
        pieces: list[str] = []
        for index, seconds in enumerate(durations):
            source = index + count
            pieces.append(
                f"[{source}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                f"apad=whole_dur={seconds},atrim=0:{seconds},asetpts=PTS-STARTPTS[a{index}]"
            )
        filter_complex = (
            f"{video_inputs}concat=n={count}:v=1:a=0[vc];"
            + ";".join(pieces)
            + f";{' '.join(f'[a{i}]' for i in range(count))}concat=n={count}:v=0:a=1[aout]"
        )
        args += [
            "-filter_complex", filter_complex,
            "-map", "[vc]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-r", "30", "-c:a", "aac", "-b:a", "128k",
            "-t", str(sum(durations)), "-movflags", "+faststart", str(out),
        ]
        try:
            subprocess.run([self._ffmpeg_path, *args], check=True, capture_output=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError("FFMPEG_COMPOSITION_FAILED") from error

    @staticmethod
    def _shots(project: JsonObject) -> list[JsonObject]:
        return list(project.get("script", {}).get("shots", []))

    @staticmethod
    def _shot_duration(shot: JsonObject) -> float:
        duration = shot.get("durationSec")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            if duration > 0:
                return float(duration)
        return 4.0


def _find_cjk_font() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    text = " ".join(str(text).split())
    if not text:
        return []
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        probe = current + char
        if font.getlength(probe) <= max_width or not current:
            current = probe
        else:
            lines.append(current)
            current = char
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and font.getlength(last + "…") > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def _draw_block(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int],
    x: int,
    y: int,
    max_width: int,
    max_lines: int,
    lines: list[str],
    line_gap: int,
) -> int:
    if not lines:
        return y
    for line in lines[:max_lines]:
        draw.text((x, y), line, font=font, fill=color)
        y += int(font.size) + line_gap
    return y


def _cover_crop(source: Image.Image, width: int, height: int) -> Image.Image:
    source = source.convert("RGB")
    scale = max(width / source.width, height / source.height)
    resized = source.resize(
        (round(source.width * scale), round(source.height * scale))
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _render_card(card: Path, font_path: str, index: int, total: int, scene_title: str,
                 shot: JsonObject, total_seconds: float,
                 background: Path | None = None) -> None:
    if background is not None and Path(background).exists():
        _render_image_card(card, font_path, index, total, scene_title, shot, Path(background))
        return
    image = Image.new("RGB", (_CARD_W, _CARD_H), _BG)
    draw = ImageDraw.Draw(image)
    font_title = ImageFont.truetype(font_path, 56)
    font_header = ImageFont.truetype(font_path, 40)
    font_body = ImageFont.truetype(font_path, 40)
    font_footer = ImageFont.truetype(font_path, 30)

    x = 84
    width = _CARD_W - 2 * x
    y = 150
    accent_bar = _ACCENT
    draw.rectangle((84, 90, 996, 94), fill=accent_bar)
    order_text = f"{index + 1:02d} / {total:02d}  ·  {scene_title or shot.get('title') or '镜头'}"
    y = _draw_block(draw, font_header, _ACCENT, x, y, width, 1,
                    _wrap(order_text, font_header, width, 1), 8)

    shot_title = str(shot.get("title") or f"镜头 {index + 1}")
    y = _draw_block(draw, font_title, _WHITE, x, y, width, 2,
                    _wrap(shot_title, font_title, width, 2), 12) + 24

    meta_parts = (shot.get("shotSize"), f"{shot.get('durationSec')}s", shot.get("emotion"))
    meta = "  ·  ".join(str(part) for part in meta_parts if part)
    if meta:
        y = _draw_block(draw, font_body, _DIM, x, y, width, 1, _wrap(meta, font_body, width, 1), 4)
        y += 12

    for _, field in (("画面", shot.get("visualDescription")),):
        value = str(field or "").strip()
        if value:
            y = _draw_block(draw, font_header, _ACCENT, x, y, width, 1, ["画面："], 6)
            y += 6
            y = _draw_block(draw, font_body, _WHITE, x, y, width, 7,
                            _wrap(value, font_body, width, 7), 14)
            y += 20

    for label, field, color in (("动作", shot.get("action"), _DIM),
                                ("对白", shot.get("dialogue"), _WHITE),
                                ("旁白", shot.get("narration"), _DIM)):
        value = str(field or "").strip()
        if value:
            y = _draw_block(draw, font_body, color, x, y, width, 4,
                            _wrap(f"{label}：{value}", font_body, width, 4), 12) + 18

    progress = f"{index + 1:02d}/{total:02d}  ·  全片约 {round(total_seconds)} 秒"
    draw.text((x, _CARD_H - 150), progress, font=font_footer, fill=_DIM)
    card.parent.mkdir(parents=True, exist_ok=True)
    image.save(card, "PNG")


def _render_image_card(card: Path, font_path: str, index: int, total: int,
                       scene_title: str, shot: JsonObject, background: Path) -> None:
    base = _cover_crop(Image.open(background), _CARD_W, _CARD_H)
    overlay = Image.new("RGBA", (_CARD_W, _CARD_H), (0, 0, 0, 0))
    shade = ImageDraw.Draw(overlay)
    shade.rectangle((0, 0, _CARD_W, 130), fill=(0, 0, 0, 130))
    shade.rectangle((0, _CARD_H - 420, _CARD_W, _CARD_H), fill=(0, 0, 0, 185))
    composited = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(composited)
    font_header = ImageFont.truetype(font_path, 34)
    font_line = ImageFont.truetype(font_path, 46)
    font_footer = ImageFont.truetype(font_path, 26)

    header = f"{index + 1:02d} / {total:02d}  ·  {scene_title or shot.get('title') or '镜头'}"
    draw.text((48, 44), header, font=font_header, fill=_ACCENT)

    text = str(shot.get("dialogue") or shot.get("narration") or "").strip()
    lines = _wrap(text, font_line, _CARD_W - 120, 4) if text else []
    if lines:
        y = _CARD_H - 330
        for line in lines:
            draw.text((60, y), line, font=font_line, fill=_WHITE)
            y += int(font_line.size) + 16

    footer = f"{index + 1:02d} / {total:02d}"
    draw.text((48, _CARD_H - 116), str(shot.get("shotSize", "")), font=font_footer,
              fill=(255, 255, 255, 220))
    footer_w = draw.textlength(footer, font=font_footer)
    draw.text((_CARD_W - 48 - footer_w, _CARD_H - 116), footer, font=font_footer, fill=_ACCENT)
    card.parent.mkdir(parents=True, exist_ok=True)
    composited.save(card, "PNG")


def _build_srt(shots: list[JsonObject], durations: list[float]) -> str:
    entries: list[str] = []
    cursor_ms = 0
    for shot, seconds in zip(shots, durations, strict=True):
        start_ms = cursor_ms
        end_ms = cursor_ms + round(seconds * 1000)
        cursor_ms = end_ms
        text = "\n".join(
            value for key in ("dialogue", "narration")
            if (value := str(shot.get(key) or "").strip())
        )
        if not text:
            continue
        stamp = f"{_srt_timestamp(start_ms)} --> {_srt_timestamp(end_ms)}"
        entry = f"{len(entries) + 1}\n{stamp}\n{text}\n"
        entries.append(entry)
    return "".join(entries)


def _srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
