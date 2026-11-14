"""Video input assembly shared by preview, synchronous calls and durable jobs.

This module owns reference resolution and the existing continuity policy. It never
submits a model request or writes project state.
"""
from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from copy import deepcopy

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject, ProjectRecord
from comicflow.production.interfaces import (
    AssetStore,
    CharacterRepository,
    DynamicVisualProvider,
    ProjectRepository,
    TextProvider,
)
from comicflow.production.reference_images import reference_asset_is_current
from comicflow.production.visual_preflight import build_preflight, failed_preflight
from comicflow.production.visual_styles import apply_video_style


class VideoPreparation:
    def __init__(
        self, repository: ProjectRepository, characters: CharacterRepository,
        video_provider: DynamicVisualProvider, text_provider: TextProvider,
        asset_store: AssetStore | None, model_revision: int,
        presign: Callable[[str], Awaitable[str]],
    ) -> None:
        self._repository = repository
        self._character_repository = characters
        self._dynamic_visual_provider = video_provider
        self._text_provider = text_provider
        self._asset_store = asset_store
        self._model_config_revision = model_revision
        self._presigned_url_cached = presign

    async def character_inputs(self, project_id: str, shot_id: str) -> list[JsonObject]:
        record = await self._require_record(project_id)
        shot = next(
            (
                item
                for item in record.project.get("script", {}).get("shots", [])
                if item["id"] == shot_id
            ),
            None,
        )
        if shot is None:
            raise DomainError("SHOT_NOT_FOUND")
        result: list[JsonObject] = []
        for character_id in shot.get("characterIds", []):
            character = await self._character_repository.get(character_id)
            if character is None:
                raise DomainError("CHARACTER_NOT_FOUND")
            card_input = {
                    key: deepcopy(character[key])
                    for key in ("id", "name", "appearance", "clothing", "personality", "voice")
                }
            card_input['revision'] = character.get('revision', 0)
            key = character.get('referenceImageObjectKey')
            if key and self._asset_store:
                card_input['referenceImageObjectKey'] = key
                card_input['referenceImageUrl'] = await self._presigned_url_cached(key)
            elif character.get('referenceImageUrl'):
                card_input['referenceImageUrl'] = character['referenceImageUrl']
            board = character.get('referenceBoard')
            if isinstance(board, dict) and reference_asset_is_current(character, board):
                card_input['referenceBoardRevision'] = {
                    key: board.get(key) for key in ('id', 'sourceReferenceId', 'createdAt')
                }
                board_key = board.get('objectKey')
                if board_key and self._asset_store:
                    card_input['referenceBoardObjectKey'] = board_key
                    card_input['referenceBoardUrl'] = await self._presigned_url_cached(board_key)
                elif board.get('url'):
                    card_input['referenceBoardUrl'] = board['url']
            views = character.get('referenceViews')
            if isinstance(views, list):
                card_views: list[JsonObject] = []
                for view in views:
                    if (not isinstance(view, dict)
                            or not reference_asset_is_current(character, view)):
                        continue
                    prepared_view = {
                        key: deepcopy(view[key])
                        for key in ('id', 'view', 'viewLabel', 'status')
                        if key in view
                    }
                    view_key = view.get('objectKey')
                    if view_key and self._asset_store:
                        prepared_view['objectKey'] = view_key
                        prepared_view['url'] = await self._presigned_url_cached(view_key)
                    elif view.get('url'):
                        prepared_view['url'] = view['url']
                    if prepared_view.get('url') or prepared_view.get('objectKey'):
                        card_views.append(prepared_view)
                if card_views:
                    card_input['referenceViews'] = card_views
            result.append(card_input)
        return result


    async def prepare(
        self, project_id: str, shot_id: str, *, expected_version: int,
        continuity_mode: str = 'auto',
    ) -> tuple[ProjectRecord, JsonObject, list[JsonObject], str | None]:
        from comicflow.providers.bailian_i2v import BailianImageToVideoProvider
        from comicflow.providers.minimax_h3 import MinimaxH3Provider

        visual_provider = self._dynamic_visual_provider
        wan = isinstance(visual_provider, BailianImageToVideoProvider)
        h3 = isinstance(visual_provider, MinimaxH3Provider)
        wan_i2v = isinstance(visual_provider, BailianImageToVideoProvider) and (
            visual_provider.generation_type == 'i2v'
        )
        record = await self._require_record(project_id)
        project = record.project
        self._require_version(project, expected_version)
        shot = self._require_shot(project, shot_id)
        script = project.get("script")
        if not isinstance(script, dict):
            raise DomainError("SCRIPT_REQUIRED")

        # Determine first frame for cascade (H3 i2va mode)
        first_frame_source: JsonObject | None = None
        cascade_from_shot_id: str | None = None

        character_inputs = await self.character_inputs(project_id, shot_id)
        shot_scene_id = shot.get("sceneId") or next(
            (s['id'] for s in script.get('scenes', []) if shot_id in s.get('shotIds', [])), None
        )
        scene = self._get_scene_by_id(script, shot_scene_id) if shot_scene_id else None
        previous_shot = (
            self._get_previous_shot_in_scene(script, shot_id, shot_scene_id)
            if shot_scene_id else None
        )
        previous_asset = (
            self._get_valid_visual_asset(project, previous_shot["id"])
            if previous_shot else None
        )
        requested_mode = str(shot.get('generationMode', 't2va')).lower()
        has_explicit_keyframe = bool(shot.get('firstFrameUrl') or shot.get('lastFrameUrl'))
        if continuity_mode not in {'auto', 'previous-tail'} or (
            continuity_mode == 'previous-tail' and (
                not h3 or previous_shot is None or has_explicit_keyframe
            )
        ):
            raise DomainError('CONTINUITY_MODE_UNAVAILABLE')
        has_character_references = any(
            c.get('referenceImageUrl') or c.get('referenceBoardUrl')
            or c.get('referenceViews') for c in character_inputs
        )
        # H3 cannot mix first_frame with reference_image. When cascading shots
        # have character references, use full-reference mode and carry the
        # previous tail as a normal continuity reference beside the character cards.
        # This ensures both continuity (via tail frame) and consistency (via character refs).
        h3_reference_reanchor = bool(
            h3 and previous_shot is not None and has_character_references
            and not has_explicit_keyframe
            and continuity_mode != 'previous-tail'
        )
        h3_cascade = h3 and previous_shot is not None and not h3_reference_reanchor
        continuity_reference: JsonObject | None = None
        if h3 and previous_shot is not None:
            previous_shot_id = str(previous_shot["id"])
            last_frame_key = previous_asset.get("lastFrameObjectKey") if previous_asset else None
            if not last_frame_key:
                raise DomainError(
                    "CASCADE_FRAME_MISSING",
                    {
                        "message": (
                            f"Previous shot {previous_shot_id} has no last frame for cascade"
                        ),
                        "previousShotId": previous_shot_id,
                        "currentShotId": shot_id,
                    },
                )
            if h3_reference_reanchor:
                continuity_reference = {
                    "id": previous_shot_id,
                    "name": "previous shot tail frame",
                    "view": "continuity-anchor",
                    "viewLabel": "previous shot tail frame continuity anchor",
                    "objectKey": last_frame_key,
                }
                if self._asset_store:
                    continuity_reference["url"] = await self._presigned_url_cached(last_frame_key)
            else:
                first_frame_source = {
                    "type": "previous_shot_last_frame",
                    "shotId": previous_shot_id,
                    "objectKey": last_frame_key,
                }
                cascade_from_shot_id = previous_shot_id

        # H3 forbids mixing reference_image with a first/last frame. A new
        # scene therefore uses a reference anchor when approved character
        # inputs exist and no explicit keyframe was supplied. Same-scene
        # continuation remains tail-frame i2va below.
        reference_mode = not wan and not h3_cascade and not has_explicit_keyframe and (
            h3_reference_reanchor
            or
            requested_mode in {'ref2va', 'r2va'}
            or (
                h3 and previous_shot is None
                and has_character_references
                and requested_mode in {'t2va', 'i2va'}
            )
            or (requested_mode == 't2va' and has_character_references)
        )
        existing = self._get_valid_visual_asset(project, shot_id) if wan else None
        existing_image = existing if existing and existing.get('mediaType') == 'image' else None
        can_cascade = h3 or wan_i2v
        # A single complete character reference is a valid Wan i2v seed. Prefer it
        # over cascading from a previous video, whose tail frame may not exist.
        single_character_seed = wan_i2v and len(character_inputs) == 1
        if shot_scene_id and not reference_mode and can_cascade and not h3_cascade and not (
            wan and (shot.get('firstFrameUrl') or existing_image or single_character_seed)
        ):
            # Get previous shot in the same scene
            prev_shot = self._get_previous_shot_in_scene(script, shot_id, shot_scene_id)

            if prev_shot is None:
                # This is the first shot in the scene - use scene background
                scene = self._get_scene_by_id(script, shot_scene_id)
                if scene and scene.get("backgroundImageObjectKey"):
                    first_frame_source = {
                        "type": "scene_background",
                        "sceneId": shot_scene_id,
                        "objectKey": scene["backgroundImageObjectKey"],
                    }
            else:
                # Use last frame from previous shot in the same scene
                prev_shot_id = prev_shot["id"]
                prev_asset = self._get_valid_visual_asset(project, prev_shot_id)

                if prev_asset:
                    last_frame_key = prev_asset.get("lastFrameObjectKey")
                    if not last_frame_key and not wan_i2v:
                        # Previous shot has no last frame - cannot cascade
                        raise DomainError(
                            "CASCADE_FRAME_MISSING",
                            {
                                "message": (
                                    f"Previous shot {prev_shot_id} has no last frame for cascade"
                                ),
                                "previousShotId": prev_shot_id,
                                "currentShotId": shot_id,
                            },
                        )
                    if last_frame_key:
                        first_frame_source = {
                            "type": "previous_shot_last_frame",
                            "shotId": prev_shot_id,
                            "objectKey": last_frame_key,
                        }
                        cascade_from_shot_id = prev_shot_id
                    # Wan i2v falls through to the scene background / character
                    # reference seeds below; it needs some first frame, not this one.

        # Pass first frame information to provider if available
        shot_with_first_frame = deepcopy(shot)
        if continuity_mode == 'previous-tail':
            shot_with_first_frame['continuityMode'] = continuity_mode
        shot_with_first_frame['scene'] = deepcopy(scene or {})
        request_seed = f'{project_id}\0{shot_id}\0{expected_version}'.encode()
        shot_with_first_frame['providerIdempotencyKey'] = (
            f'comicflow-{hashlib.sha256(request_seed).hexdigest()[:40]}'
        )
        provider_character_inputs = character_inputs
        if h3_cascade:
            shot_with_first_frame['generationMode'] = 'i2va'
            # H3 accepts either a keyframe or reference pictures, not both. The
            # previous tail is the continuity source for subsequent shots; the
            # character cards remain available as text metadata to the Skill.
            shot_with_first_frame.pop('referenceImages', None)
            provider_character_inputs = [
                {
                    key: value for key, value in character.items()
                    if key not in {
                        'referenceImageUrl', 'referenceImageObjectKey', 'referenceViews',
                        'referenceBoardUrl', 'referenceBoardObjectKey'
                    }
                }
                for character in character_inputs
            ]
        if reference_mode:
            shot_with_first_frame['generationMode'] = 'ref2va'
            reference_images: list[JsonObject] = []
            if continuity_reference:
                reference_images.append(continuity_reference)
            if scene and scene.get('backgroundImageObjectKey') and self._asset_store:
                reference_images.append({
                    'id': scene['id'], 'name': scene.get('title', ''),
                    'view': 'scene-anchor',
                    'viewLabel': 'approved scene background',
                    'objectKey': scene['backgroundImageObjectKey'],
                    'url': await self._presigned_url_cached(scene['backgroundImageObjectKey']),
                })
            if reference_images:
                shot_with_first_frame['referenceImages'] = reference_images
        if first_frame_source:
            shot_with_first_frame["firstFrameSource"] = first_frame_source
            shot_with_first_frame["firstFrameObjectKey"] = first_frame_source.get("objectKey")
            if self._asset_store:
                shot_with_first_frame['firstFrameUrl'] = await self._presigned_url_cached(
                    first_frame_source['objectKey']
                )

        if wan_i2v:
            if not shot_with_first_frame.get('firstFrameUrl') and existing_image:
                shot_with_first_frame['firstFrameObjectKey'] = existing_image.get('objectKey')
                shot_with_first_frame['firstFrameUrl'] = (
                    await self._presigned_url_cached(existing_image['objectKey'])
                    if existing_image.get('objectKey') and self._asset_store
                    else existing_image.get('sourceUrl')
                )
            if not shot_with_first_frame.get('firstFrameUrl') and len(character_inputs) == 1:
                shot_with_first_frame['firstFrameObjectKey'] = character_inputs[0].get(
                    'referenceImageObjectKey'
                )
                shot_with_first_frame['firstFrameUrl'] = character_inputs[0].get(
                    'referenceImageUrl'
                )
            # Wan i2v cannot run without a first frame. For a multi-character shot the
            # scene background is the better seed than any single character portrait,
            # which would bias the frame toward one of them.
            if not shot_with_first_frame.get('firstFrameUrl') and scene and scene.get(
                'backgroundImageObjectKey'
            ):
                background_key = scene['backgroundImageObjectKey']
                shot_with_first_frame['firstFrameObjectKey'] = background_key
                if self._asset_store:
                    shot_with_first_frame['firstFrameUrl'] = (
                        await self._presigned_url_cached(background_key)
                    )
            if not shot_with_first_frame.get('firstFrameUrl'):
                seed = next(
                    (c for c in character_inputs if c.get('referenceImageObjectKey')
                     or c.get('referenceImageUrl')),
                    None,
                )
                if seed:
                    shot_with_first_frame['firstFrameObjectKey'] = seed.get(
                        'referenceImageObjectKey'
                    )
                    shot_with_first_frame['firstFrameUrl'] = seed.get('referenceImageUrl')

        return (record, apply_video_style(shot_with_first_frame, project),
                provider_character_inputs, cascade_from_shot_id)


    async def preview(
        self, project_id: str, shot_id: str, *, expected_version: int,
        continuity_mode: str = 'auto',
    ) -> JsonObject:
        try:
            record, shot, characters, _ = await self.prepare(
                project_id, shot_id, expected_version=expected_version,
                continuity_mode=continuity_mode,
            )
            return await build_preflight(
                self._dynamic_visual_provider, self._text_provider, record.project,
                shot, characters, self._model_config_revision, self._asset_store,
            )
        except DomainError as error:
            if error.code in {'PROJECT_NOT_FOUND', 'SHOT_NOT_FOUND', 'VERSION_CONFLICT'}:
                raise
            return failed_preflight(error.code)


    async def _require_record(self, project_id: str) -> ProjectRecord:
        record = await self._repository.get(project_id)
        if record is None:
            raise DomainError("PROJECT_NOT_FOUND")
        return record


    @staticmethod
    def _require_version(project: JsonObject, expected_version: int) -> None:
        if project["version"] != expected_version:
            raise DomainError("VERSION_CONFLICT")


    @staticmethod
    def _require_shot(project: JsonObject, shot_id: str) -> JsonObject:
        shot = next(
            (item for item in project.get("script", {}).get("shots", []) if item["id"] == shot_id),
            None,
        )
        if shot is None:
            raise DomainError("SHOT_NOT_FOUND")
        return dict(shot)


    @staticmethod
    def _get_scene_by_id(script: JsonObject, scene_id: str) -> JsonObject | None:
        """Get a scene by its ID from the script."""
        scenes = script.get("scenes", [])
        for scene in scenes:
            if isinstance(scene, dict) and scene.get("id") == scene_id:
                return scene
        return None


    @staticmethod
    def _get_previous_shot_in_scene(
        script: JsonObject, current_shot_id: str, scene_id: str
    ) -> JsonObject | None:
        """Get the previous shot in the same scene, or None if this is the first shot."""
        scene = next(
            (s for s in script.get("scenes", [])
             if isinstance(s, dict) and s.get("id") == scene_id),
            None,
        )
        if not scene or not isinstance(scene.get("shotIds"), list):
            return None

        shot_ids = scene["shotIds"]
        try:
            current_index = shot_ids.index(current_shot_id)
            if current_index > 0:
                prev_shot_id = shot_ids[current_index - 1]
                # Get the shot object from the shots array
                shots = script.get("shots", [])
                for shot in shots:
                    if isinstance(shot, dict) and shot.get("id") == prev_shot_id:
                        return shot
        except ValueError:
            # Current shot not in scene
            pass
        return None


    @staticmethod
    def _get_valid_visual_asset(project: JsonObject, shot_id: str) -> JsonObject | None:
        """Get the valid visual asset for a shot, or None if not found."""
        assets = project.get("visualAssets", [])
        for asset in assets:
            if isinstance(asset, dict) and asset.get("shotId") == shot_id and asset.get("valid"):
                return asset
        return None
