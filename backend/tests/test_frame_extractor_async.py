import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from comicflow.utils.frame_extractor import FrameExtractor


@pytest.mark.parametrize("method", ["extract_first_frame", "extract_last_frame"])
async def test_frame_extraction_does_not_block_the_event_loop(monkeypatch, method):
    started = threading.Event()
    released = threading.Event()
    overlapped = []

    def run(command, **_kwargs):
        started.set()
        overlapped.append(released.wait(timeout=2))
        Path(command[-1]).write_bytes(b"jpeg-test-frame")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("comicflow.utils.frame_extractor.subprocess.run", run)
    task = asyncio.create_task(getattr(FrameExtractor, method)("fixture.mp4"))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        released.set()
        assert await task == b"jpeg-test-frame"
        assert overlapped == [True], "FFmpeg blocked the async request loop"
    finally:
        released.set()
        await task
