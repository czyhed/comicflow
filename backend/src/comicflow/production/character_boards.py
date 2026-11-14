"""The single generated board's input, byte validation and explicit adoption rules."""
import io
from copy import deepcopy
from typing import Any

from PIL import Image

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject
from comicflow.production.reference_images import reference_asset_is_current
from comicflow.providers.h3_inputs import MAX_IMAGE_BYTES, image_data


def require_board_size(size: str) -> None:
    try:
        width, height = map(int, size.lower().replace('x', '*').split('*'))
        if not (256 <= width <= 5760 and 256 <= height <= 5760 and 1 <= width / height <= 2.5):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise DomainError('REFERENCE_BOARD_SIZE_INVALID') from None


async def validate_board_bytes(asset: JsonObject, store: Any) -> JsonObject:
    if not asset.get('objectKey') or not callable(getattr(store, 'get_bytes', None)):
        raise DomainError('REFERENCE_STORAGE_UNAVAILABLE')
    content = await store.get_bytes(asset['objectKey'], MAX_IMAGE_BYTES)
    image_data(content)  # Same decode/format/size safety limits as H3 input.
    with Image.open(io.BytesIO(content)) as image:
        if image.width < image.height:
            raise RuntimeError('REFERENCE_IMAGE_INVALID')
        return {'width': image.width, 'height': image.height}


def approve_board(character: JsonObject, project: JsonObject, candidate_id: str,
                  expected_version: int) -> bool:
    """Called under the image store's project/character transaction. False is a replay."""
    current = character.get('referenceBoard') or {}
    if current.get('id') == candidate_id and reference_asset_is_current(character, current):
        if current.get('styleSnapshot') == project.get('visualStyleProfile'):
            return False
    if project['version'] != expected_version:
        raise DomainError('VERSION_CONFLICT')
    candidate = character.get('referenceBoardCandidate')
    if not isinstance(candidate, dict) or candidate.get('id') != candidate_id:
        raise DomainError('REFERENCE_CANDIDATE_NOT_FOUND')
    board = deepcopy(candidate)
    if board.get('status') != 'candidate':
        raise DomainError('REFERENCE_BOARD_STALE')
    board['status'] = 'approved'
    if (not reference_asset_is_current(character, board)
            or board.get('styleSnapshot') != project.get('visualStyleProfile')):
        raise DomainError('REFERENCE_BOARD_STALE')
    character.update(referenceBoard=board, referenceBoardCandidate=None)
    project['version'] += 1
    return True
