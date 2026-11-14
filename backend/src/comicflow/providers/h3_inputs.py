"""Prepare H3 reference images locally before spending text or video quota."""

from __future__ import annotations

import base64
import binascii
import io
import ipaddress
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from comicflow.domain.models import JsonObject

MAX_IMAGE_BYTES = 30 * 1024 * 1024


def image_data(content: bytes) -> str:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise RuntimeError('REFERENCE_IMAGE_INVALID')
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or not all(
                256 <= size <= 5760 for size in image.size
            ) or not 0.4 <= image.width / image.height <= 2.5:
                raise RuntimeError('REFERENCE_IMAGE_INVALID')
            buffer = io.BytesIO()
            image.convert('RGB').save(buffer, format='PNG')
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise RuntimeError('REFERENCE_IMAGE_INVALID') from error
    if buffer.tell() > MAX_IMAGE_BYTES:
        raise RuntimeError('REFERENCE_IMAGE_INVALID')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def local_url(value: str) -> bool:
    host = (urlsplit(value).hostname or '').lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local')):
        return True
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        return False


async def prepare_images(
    shot: JsonObject, characters: list[JsonObject], store: Any,
) -> tuple[JsonObject, list[JsonObject]]:
    prepared, cards = deepcopy(shot), deepcopy(characters)
    encoded: dict[str, str] = {}
    input_size = 0

    async def prepare(item: JsonObject, url_field: str, key_field: str) -> None:
        nonlocal input_size
        url, key = item.get(url_field), item.get(key_field)
        if key:
            if key not in encoded:
                if store is None or not callable(getattr(store, 'get_bytes', None)):
                    raise RuntimeError('H3_REFERENCE_UNREADABLE')
                try:
                    content = await store.get_bytes(str(key), MAX_IMAGE_BYTES)
                except Exception as error:
                    raise RuntimeError('H3_REFERENCE_UNREADABLE') from error
                encoded[key] = image_data(content)
            url = encoded[key]
        elif isinstance(url, str) and url.startswith('data:'):
            try:
                header, data = url.split(',', 1)
                if header not in {
                    'data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64',
                } or len(data) > MAX_IMAGE_BYTES * 4 // 3 + 4:
                    raise ValueError('image encoding')
                url = image_data(base64.b64decode(data, validate=True))
            except (ValueError, binascii.Error) as error:
                raise RuntimeError('REFERENCE_IMAGE_INVALID') from error
        elif isinstance(url, str) and local_url(url):
            raise RuntimeError('H3_REFERENCE_UNREACHABLE')
        if url:
            item[url_field] = url
            input_size += len(str(url).encode('utf-8'))
            # Leave ample space for JSON, metadata and the <=7000-character prompt.
            if input_size > 63 * 1024 * 1024:
                raise RuntimeError('H3_REFERENCE_TOO_LARGE')

    for frame in ('first', 'last'):
        await prepare(prepared, f'{frame}FrameUrl', f'{frame}FrameObjectKey')
    for card in cards:
        await prepare(card, 'referenceBoardUrl', 'referenceBoardObjectKey')
        await prepare(card, 'referenceImageUrl', 'referenceImageObjectKey')
        views = card.get('referenceViews')
        if isinstance(views, list):
            for view in views:
                if isinstance(view, dict):
                    await prepare(view, 'url', 'objectKey')
    for reference in prepared.get('referenceImages', []):
        await prepare(reference, 'url', 'objectKey')
    return prepared, cards


def text_metadata(value: Any) -> Any:
    """The text model sees metadata/labels, never image bytes or signed asset URLs."""
    if isinstance(value, dict):
        return {key: text_metadata(item) for key, item in value.items()
                if not key.lower().endswith(('url', 'objectkey'))}
    if isinstance(value, list):
        return [text_metadata(item) for item in value]
    return value
