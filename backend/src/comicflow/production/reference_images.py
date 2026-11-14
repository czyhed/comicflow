"""Shared image request validation and metadata for character and scene references."""
from collections.abc import Awaitable, Callable
from copy import deepcopy
from uuid import uuid4

from comicflow.domain.models import JsonObject
from comicflow.production.interfaces import AssetStore, DynamicVisualProvider
from comicflow.providers.drama_skills import prepare_visual_asset_request


def reference_asset_is_current(character: JsonObject, asset: JsonObject) -> bool:
    """Check known provenance without inventing metadata for historical assets."""
    if asset.get('status', 'approved') != 'approved':
        return False
    if 'sourceImageVersion' in asset and (
        not asset['sourceImageVersion']
        or asset['sourceImageVersion'] != character.get('referenceImageVersion')
    ):
        return False
    source = character.get('referenceImageObjectKey') or character.get('referenceImageUrl')
    # View sourceReferenceId has always meant the main object key (or external URL).
    # Historical board sourceReferenceId can instead be an opaque asset ID.
    if (asset.get('view') or asset.get('generationMode') == 'single-edit-board') and (
        asset.get('sourceReferenceId')
    ):
        if asset['sourceReferenceId'] != source:
            return False
    if asset.get('generationMode') in {'single-edit-board', 'single-text-board'} and (
        asset.get('sourceAppearance') != character.get('appearance')
        or asset.get('sourceClothing') != character.get('clothing')
    ):
        return False
    keys, layout = asset.get('sourceObjectKeys'), asset.get('layout')
    if isinstance(keys, list) and isinstance(layout, list) and layout[:1] == ['main']:
        views = {v.get('view'): v for v in character.get('referenceViews', [])
                 if isinstance(v, dict)}
        current_keys = [character.get('referenceImageObjectKey')]
        for view in layout[1:]:
            item = views.get(view, {})
            if not reference_asset_is_current(character, item):
                return False
            current_keys.append(item.get('objectKey'))
        if not all(current_keys) or keys != current_keys:
            return False
    return True


def invalidate_reference_board(character: JsonObject) -> None:
    """Retain the previous artifact for inspection, but stop using it as input."""
    for field in ('referenceBoard', 'referenceBoardCandidate'):
        board = character.get(field)
        if isinstance(board, dict):
            board['status'] = 'stale'


async def generate_reference_image(
    shot: JsonObject, *, provider: DynamicVisualProvider | None,
    asset_store: AssetStore | None, presign: Callable[[str], Awaitable[str]],
) -> JsonObject:
    if provider is None:
        raise RuntimeError("REFERENCE_IMAGE_PROVIDER_REQUIRED")
    prepared = prepare_visual_asset_request(shot)
    result = await provider.generate(prepared, [])
    return await normalize_reference_image(
        prepared, result, asset_store=asset_store, presign=presign)


async def normalize_reference_image(
    prepared: JsonObject, result: JsonObject, *, asset_store: AssetStore | None,
    presign: Callable[[str], Awaitable[str]],
) -> JsonObject:
    if result.get("mediaType") != "image":
        raise RuntimeError("REFERENCE_IMAGE_INVALID")
    key = result.get("objectKey")
    url: object
    if key and asset_store:
        url = await presign(key)
    else:
        url = result.get("sourceUrl")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        raise RuntimeError("REFERENCE_IMAGE_INVALID")
    from urllib.parse import urlparse
    if urlparse(url).path.lower().endswith((".mp4", ".mov", ".webm")):
        raise RuntimeError("REFERENCE_IMAGE_INVALID")
    return {
        "id": result.get("id") or f"image-{uuid4().hex[:12]}",
        "url": url,
        "objectKey": key,
        "provider": result.get("provider"),
        "modelVersion": result.get("modelVersion"),
        "mediaType": "image",
        "skillExecution": deepcopy(prepared["skillExecution"]),
        **({'styleSnapshot': deepcopy(prepared['styleSnapshot']),
            'styleApplication': deepcopy(prepared['styleApplication'])}
           if prepared.get('styleSnapshot') else {}),
    }
