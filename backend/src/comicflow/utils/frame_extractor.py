"""Video frame extraction utilities."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path


class FrameExtractor:
    """Extract frames from video files using ffmpeg."""

    @staticmethod
    async def extract_last_frame(video_path: str | Path) -> bytes:
        """Extract the last frame from a video file.

        Args:
            video_path: Path to the video file (local path or downloaded file)

        Returns:
            JPEG image data as bytes

        Raises:
            RuntimeError: If ffmpeg extraction fails
        """
        return await asyncio.to_thread(FrameExtractor._extract_last_frame, video_path)

    @staticmethod
    def _extract_last_frame(video_path: str | Path) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            output_path = tmp.name

        try:
            # Use ffmpeg to extract the last frame
            # -sseof -1: seek to 1 second before end
            # -frames:v 1: extract only 1 frame
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-sseof",
                    "-1",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",  # High quality JPEG
                    "-y",  # Overwrite output
                    output_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed: {result.stderr or result.stdout}"
                )

            # Read the extracted frame
            with open(output_path, "rb") as f:
                return f.read()

        finally:
            # Clean up temp file
            Path(output_path).unlink(missing_ok=True)

    @staticmethod
    async def extract_first_frame(video_path: str | Path) -> bytes:
        """Extract the first frame from a video file.

        Args:
            video_path: Path to the video file

        Returns:
            JPEG image data as bytes

        Raises:
            RuntimeError: If ffmpeg extraction fails
        """
        return await asyncio.to_thread(FrameExtractor._extract_first_frame, video_path)

    @staticmethod
    def _extract_first_frame(video_path: str | Path) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            output_path = tmp.name

        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    "-y",
                    output_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed: {result.stderr or result.stdout}"
                )

            with open(output_path, "rb") as f:
                return f.read()

        finally:
            Path(output_path).unlink(missing_ok=True)
