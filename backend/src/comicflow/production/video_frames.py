"""Persist video endpoint frames through the configured asset store."""
from __future__ import annotations

import hashlib
import logging

from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore

_logger = logging.getLogger(__name__)
_MAX_VIDEO_READ_BYTES = 200 * 1024 * 1024


async def extract_cascade_frames(
    store: AssetStore | None, asset: JsonObject, shot_id: str
) -> None:
    """Store the first and last frame of a freshly generated video asset.

    The video is read through the asset store's internal client. Presigned URLs
    rewrite the host to ``S3_PUBLIC_ENDPOINT``, which is not routable from inside
    the API container, so fetching them here would always fail.

    Extraction failures do not invalidate the video, but they are recorded on the
    asset and logged so a missing tail frame cannot pass unnoticed.
    """
    video_object_key = asset.get("objectKey")
    if store is None or not video_object_key:
        return
    if not hasattr(store, "get_bytes"):
        asset["frameExtractionError"] = "ASSET_STORE_READ_UNSUPPORTED"
        _logger.warning(
            "Cascade frame extraction unavailable: shotId=%s reason=%s",
            shot_id,
            "ASSET_STORE_READ_UNSUPPORTED",
        )
        return

    import os
    import tempfile

    from comicflow.utils.frame_extractor import FrameExtractor

    try:
        content = await store.get_bytes(str(video_object_key), _MAX_VIDEO_READ_BYTES)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            first_frame = await FrameExtractor.extract_first_frame(tmp_path)
            frame_scope = hashlib.sha256(str(video_object_key).encode()).hexdigest()
            first_frame_key = f"visuals/{shot_id}/{frame_scope}/first_frame.jpg"
            await store.put_bytes(first_frame_key, first_frame, "image/jpeg")
            asset["firstFrameObjectKey"] = first_frame_key

            last_frame = await FrameExtractor.extract_last_frame(tmp_path)
            last_frame_key = f"visuals/{shot_id}/{frame_scope}/last_frame.jpg"
            await store.put_bytes(last_frame_key, last_frame, "image/jpeg")
            asset["lastFrameObjectKey"] = last_frame_key
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception as error:
        # A missing tail frame breaks the next shot's cascade, so surface it
        # without discarding the video that was already paid for.
        asset["frameExtractionError"] = type(error).__name__
        _logger.warning(
            "Cascade frame extraction failed: shotId=%s error=%s",
            shot_id,
            type(error).__name__,
        )
