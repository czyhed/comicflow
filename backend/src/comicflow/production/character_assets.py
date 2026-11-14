"""Character cards and reference assets, independent of production-stage orchestration."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from copy import deepcopy
from uuid import uuid4

from comicflow.domain.errors import DomainError
from comicflow.domain.models import Actor, JsonObject, ProjectRecord
from comicflow.production.interfaces import (
    AssetStore,
    CharacterRepository,
    DynamicVisualProvider,
    ProjectRepository,
    TextProvider,
)
from comicflow.production.reference_images import (
    generate_reference_image,
    invalidate_reference_board,
    reference_asset_is_current,
)
from comicflow.production.visual_styles import style_instructions
from comicflow.providers.character_prompt import character_prompt_fields, validate_character_prompt
from comicflow.providers.error_mapping import map_provider_error
from comicflow.providers.text_errors import TextRequestError

_logger = logging.getLogger(__name__)

class CharacterAssets:
    def __init__(
        self, *, repository: ProjectRepository, characters: CharacterRepository,
        image_provider: DynamicVisualProvider | None, text_provider: TextProvider,
        asset_store: AssetStore | None, locks: dict[str, asyncio.Lock],
        presign: Callable[[str], Awaitable[str]],
    ) -> None:
        self._repository = repository
        self._character_repository = characters
        self._reference_image_provider = image_provider
        self._text_provider = text_provider
        self._asset_store = asset_store
        self._generation_locks = locks
        self._presigned_url_cached = presign

    async def list_character_templates(self) -> list[JsonObject]:
        characters = await self._character_repository.list()
        return [deepcopy(item) for item in characters if item.get("source") == "system"]

    async def list_project_characters(self, project_id: str) -> list[JsonObject]:
        record = await self._require_record(project_id)
        referenced = {
            cid for shot in (record.project.get('script') or {}).get('shots', [])
            for cid in shot.get('characterIds', [])
        }
        cards = [deepcopy(card) for card in await self._character_repository.list()
                 if card.get('projectId') == project_id or card['id'] in referenced]
        for card in cards:
            if card.get('referenceImageObjectKey') and self._asset_store:
                card['referenceImageUrl'] = await self._presigned_url_cached(
                    card['referenceImageObjectKey']
                )
            candidate = card.get('referenceImageCandidate')
            if isinstance(candidate, dict) and candidate.get('objectKey') and self._asset_store:
                candidate['url'] = await self._presigned_url_cached(candidate['objectKey'])
            for view in card.get('referenceViews', []):
                if isinstance(view, dict) and view.get('objectKey') and self._asset_store:
                    view['url'] = await self._presigned_url_cached(view['objectKey'])
            board_candidate = card.get('referenceBoardCandidate')
            if isinstance(board_candidate, dict):
                check = {**board_candidate, 'status': 'approved'}
                if (not reference_asset_is_current(card, check)
                        or check.get('styleSnapshot') != record.project.get('visualStyleProfile')):
                    board_candidate['status'] = 'stale'
                if board_candidate.get('objectKey') and self._asset_store:
                    board_candidate['url'] = await self._presigned_url_cached(
                        board_candidate['objectKey'])
            board = card.get('referenceBoard')
            if isinstance(board, dict):
                if not reference_asset_is_current(card, board):
                    board['status'] = 'stale'
                if board.get('objectKey') and self._asset_store:
                    board['url'] = await self._presigned_url_cached(board['objectKey'])
        return cards

    async def preview_character_prompt(
        self, project_id: str, *, fields: JsonObject, instructions: str,
        character_id: str | None, expected_version: int, expected_revision: int,
        purpose: str = 'full', output_fields: list[str] | None = None,
    ) -> JsonObject:
        try:
            selected = character_prompt_fields(purpose, output_fields)
        except ValueError as error:
            raise DomainError('CHARACTER_PROMPT_INVALID') from error
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        if character_id:
            card = await self._character_repository.get(character_id)
            if card is None:
                raise DomainError('CHARACTER_NOT_FOUND')
            if card.get('projectId') != project_id:
                raise DomainError('CHARACTER_ACCESS_DENIED')
            if card.get('revision', 0) != expected_revision:
                raise DomainError('CHARACTER_VERSION_CONFLICT')
        generate = getattr(self._text_provider, 'generate_character_prompt', None)
        if not callable(generate):
            raise DomainError('CHARACTER_PROMPT_PROVIDER_REQUIRED')
        if purpose == 'reference-image' and any(
            not str(fields.get(key) or '').strip() for key in ('appearance', 'clothing')
        ):
            raise DomainError('CHARACTER_FIELDS_REQUIRED')
        script = record.project.get('script') or {}
        related = [shot for shot in script.get('shots', [])
                   if (character_id and character_id in shot.get('characterIds', []))
                   or (not character_id and fields['name'] in shot.get('characters', []))]
        # Send creative text only; asset URLs, voice settings and credentials are irrelevant.
        shot_fields = ('id', 'title', 'visualDescription', 'action', 'emotion', 'dialogue',
                       'narration', 'visualStyle')
        context: JsonObject = {'fields': deepcopy(fields), 'instructions': instructions}
        if purpose != 'reference-image':
            context.update({
                'story': str(record.project.get('generatedStoryText')
                             or record.project.get('storyText')
                             or record.project.get('input', {}).get('story', ''))[:12000],
                'scriptTitle': script.get('title', ''),
                'shots': [{key: str(shot[key])[:2000] for key in shot_fields if key in shot}
                          for shot in related[:30]],
            })
        if purpose != 'full':
            context.update(purpose=purpose, outputFields=list(selected))
            # Personality does not describe image appearance; old image prose does not
            # establish story facts when editing character settings.
            context['fields'].pop(
                'personality' if purpose == 'reference-image' else 'referenceImagePrompt', None)
        if record.project.get('visualStyleProfile') is not None:
            profile = record.project['visualStyleProfile']
            # Validate the persisted style even when sending only its image-relevant fields.
            style_text = style_instructions(profile, 'character-prompt')
            if purpose == 'full':
                context['visualStyleProfile'] = deepcopy(profile)
                context['instructions'] = instructions + '\n' + style_text
            else:
                context['visualStyle'] = {key: profile[key] for key in (
                    'name', 'medium', 'rendering', 'lighting', 'avoid')}
        try:
            draft = validate_character_prompt(
                await generate(context), purpose=purpose, output_fields=list(selected))
        except RuntimeError as error:
            detail = deepcopy(error.detail) if isinstance(error, TextRequestError) else {}
            raise DomainError(map_provider_error(str(error)), detail) from error
        current = await self._require_record(project_id)
        self._require_version(current.project, expected_version)
        if character_id:
            latest = await self._character_repository.get(character_id)
            if latest is None or latest.get('revision', 0) != expected_revision:
                raise DomainError('CHARACTER_VERSION_CONFLICT')
        return {'draft': {'name': fields['name'], **draft}, 'expectedVersion': expected_version,
                'expectedRevision': expected_revision if character_id else None}

    async def save_project_character(
        self, project_id: str, input_data: JsonObject, *, character_id: str | None = None
    ) -> JsonObject:
        record = await self._require_record(project_id)
        if 'expectedVersion' in input_data:
            self._require_version(record.project, input_data['expectedVersion'])
        actor = Actor.guest(record.guest_session['id'])
        if character_id:
            card = await self._character_repository.get(character_id)
            if card is None:
                raise DomainError('CHARACTER_NOT_FOUND')
            if card.get('projectId') != project_id:
                raise DomainError('CHARACTER_ACCESS_DENIED')
            return await self.update_character(character_id, input_data, actor=actor)
        return await self.create_character(input_data, actor=actor, project_id=project_id)

    async def create_character(
        self, input_data: JsonObject, *, actor: Actor, project_id: str | None = None
    ) -> JsonObject:
        required = ("name", "appearance", "clothing", "personality", "voice")
        if any(not input_data.get(field) for field in required):
            raise DomainError("CHARACTER_FIELDS_REQUIRED")
        prompt = input_data.get('referenceImagePrompt', '')
        if not isinstance(prompt, str) or len(prompt) > 4000:
            raise DomainError('CHARACTER_FIELDS_REQUIRED')
        if actor.type == "guest" and not project_id:
            raise DomainError("PROJECT_REQUIRED")
        if project_id:
            await self._require_record(project_id)

        character: JsonObject = {
            **deepcopy(input_data),
            "id": f"chr_{uuid4().hex[:12]}",
            "source": "user" if actor.type == "user" else "temporary",
            "ownerType": actor.type,
            "ownerId": actor.id,
            "projectId": project_id if actor.type == "guest" else None,
            "revision": 0,
            "referenceImagePrompt": prompt,
        }
        character.pop('expectedVersion', None)
        character.pop('expectedRevision', None)
        await self._character_repository.save(character)
        return deepcopy(character)

    async def update_character(
        self, character_id: str, input_data: JsonObject, *, actor: Actor
    ) -> JsonObject:
        character = await self._character_repository.get(character_id)
        if character is None:
            raise DomainError("CHARACTER_NOT_FOUND")
        expected_character = deepcopy(character)
        if character.get("ownerType") != actor.type or character.get("ownerId") != actor.id:
            raise DomainError("CHARACTER_ACCESS_DENIED")
        revision = character.get('revision', 0)
        if input_data.get('expectedRevision', revision) != revision:
            raise DomainError('CHARACTER_VERSION_CONFLICT')
        required = ("name", "appearance", "clothing", "personality", "voice")
        if any(not input_data.get(field) for field in required):
            raise DomainError("CHARACTER_FIELDS_REQUIRED")
        prompt = input_data.get('referenceImagePrompt', character.get('referenceImagePrompt', ''))
        if not isinstance(prompt, str) or len(prompt) > 4000:
            raise DomainError('CHARACTER_FIELDS_REQUIRED')
        if any(character.get(k) != input_data[k] for k in ('appearance', 'clothing')):
            invalidate_reference_board(character)
            for field in (
                'referenceImageUrl', 'referenceImageObjectKey', 'referenceImageMediaType',
                'referenceImageVersion', 'referenceImageSkillExecution',
                'referenceImageStyleSnapshot', 'referenceImageCandidate', 'referenceViews',
            ):
                character.pop(field, None)
            character['referenceImageStatus'] = 'none'
        character.update({field: deepcopy(input_data[field]) for field in required})
        character['referenceImagePrompt'] = prompt
        character['revision'] = revision + 1
        await self._character_repository.save(character, expected=expected_character)
        return deepcopy(character)

    async def delete_character(self, character_id: str, *, actor: Actor) -> None:
        character = await self._character_repository.get(character_id)
        if character is None:
            raise DomainError("CHARACTER_NOT_FOUND")
        if character.get("ownerType") != actor.type or character.get("ownerId") != actor.id:
            raise DomainError("CHARACTER_ACCESS_DENIED")
        await self._character_repository.delete(character_id)

    async def approve_character_reference_candidate(
        self,
        project_id: str,
        character_id: str,
        candidate_id: str,
        *,
        expected_version: int,
    ) -> JsonObject:
        record = await self._require_record(project_id)
        self._require_version(record.project, expected_version)
        character = await self._character_repository.get(character_id)
        if not character or character.get('projectId') != project_id:
            raise DomainError('CHARACTER_ACCESS_DENIED')
        expected_character = deepcopy(character)
        candidate = character.get('referenceImageCandidate')
        if not isinstance(candidate, dict) or candidate.get('id') != candidate_id:
            raise DomainError('REFERENCE_CANDIDATE_NOT_FOUND')
        if candidate.get('characterRevision', 0) != character.get('revision', 0):
            raise DomainError('REFERENCE_CANDIDATE_VERSION_CONFLICT')
        if candidate.get('mediaType') != 'image' or not candidate.get('url'):
            raise DomainError('REFERENCE_CANDIDATE_NOT_FOUND')
        invalidate_reference_board(character)
        character['referenceImageVersion'] = candidate_id
        character['referenceImageUrl'] = candidate['url']
        character['referenceImageObjectKey'] = candidate.get('objectKey')
        character['referenceImageMediaType'] = 'image'
        character['referenceImageSkillExecution'] = deepcopy(
            candidate.get('skillExecution')
        ) if isinstance(candidate.get('skillExecution'), dict) else None
        character['referenceImageStyleSnapshot'] = deepcopy(candidate.get('styleSnapshot'))
        character['referenceImageStatus'] = 'approved'
        character['referenceImageCandidate'] = None
        character['referenceViews'] = []
        await self._character_repository.save(character, expected=expected_character)
        record.project['version'] += 1
        await self._repository.save(record)
        return {
            'character': deepcopy(character),
            'projectVersion': record.project['version'],
        }

    async def _compose_character_reference_board(
        self, character: JsonObject, project_id: str, character_id: str
    ) -> JsonObject | None:
        """Build one clean local board from the approved character images."""
        store = self._asset_store
        if store is None or not callable(getattr(store, 'get_bytes', None)):
            return None
        main_key = character.get('referenceImageObjectKey')
        views = {item.get('view'): item for item in character.get('referenceViews', [])
                 if isinstance(item, dict)}
        keys = [main_key, views.get('front', {}).get('objectKey'),
                views.get('three-quarter', {}).get('objectKey'),
                views.get('profile', {}).get('objectKey')]
        if not all(isinstance(key, str) and key for key in keys):
            return None
        try:
            import io

            from PIL import Image
            images = [Image.open(io.BytesIO(await store.get_bytes(str(key)))).convert('RGB')
                      for key in keys]
            cell_w, cell_h = 768, 768
            # A four-cell strip exceeds H3's 2.5:1 reference-image aspect limit.
            board = Image.new('RGB', (cell_w * 2, cell_h * 2), 'white')
            for index, image in enumerate(images):
                image.thumbnail((cell_w - 32, cell_h - 32))
                board.paste(image, ((index % 2) * cell_w + (cell_w - image.width) // 2,
                                    (index // 2) * cell_h + (cell_h - image.height) // 2))
            output = io.BytesIO()
            board.save(output, format='JPEG', quality=92, optimize=True)
            object_key = (f'projects/{project_id}/characters/{character_id}/'
                          f'reference-board-{uuid4().hex}.jpg')
            await store.put_bytes(object_key, output.getvalue(), 'image/jpeg')
            return {'objectKey': object_key,
                    'url': await self._presigned_url_cached(object_key),
                    'mediaType': 'image',
                    'status': 'approved',
                    'sourceReferenceId': main_key,
                    **({'sourceImageVersion': character['referenceImageVersion']}
                       if character.get('referenceImageVersion') else {}),
                    'columns': 2,
                    'layout': ['main', 'front', 'three-quarter', 'profile'],
                    'sourceObjectKeys': keys}
        except Exception as error:
            _logger.warning('character reference board composition failed: %s', error)
            return None

    async def _generate_character_reference(
        self, character: JsonObject, project_id: str, *, generation_id: str | None = None,
        style_profile: JsonObject | None = None,
    ) -> JsonObject:
        return await self._reference_image(character_reference_request(
            character, generation_id or f"{project_id}_char_ref_{character['id']}", style_profile))

    async def _reference_image(self, shot: JsonObject) -> JsonObject:
        return await generate_reference_image(
            shot, provider=self._reference_image_provider, asset_store=self._asset_store,
            presign=self._presigned_url_cached,
        )

    async def _require_record(self, project_id: str) -> ProjectRecord:
        record = await self._repository.get(project_id)
        if record is None:
            raise DomainError("PROJECT_NOT_FOUND")
        return record

    @staticmethod
    def _require_version(project: JsonObject, expected_version: int) -> None:
        if project["version"] != expected_version:
            raise DomainError("VERSION_CONFLICT")


def character_reference_request(character: JsonObject, generation_id: str,
                            style_profile: JsonObject | None) -> JsonObject:
    styled = style_profile is not None
    return {
        "id": generation_id,
        "imagePurpose": "character-reference", "durationSec": 4,
        "styleSnapshot": deepcopy(style_profile),
        "visualDescription": character.get('referenceImagePrompt') or (
            f"角色：{character.get('name', '')}。外观：{character.get('appearance', '')}。"
            f"服装：{character.get('clothing', '')}。" if styled else
            f"角色：{character.get('name', '')}。外观：{character.get('appearance', '')}。"
            f"服装：{character.get('clothing', '')}。"
            "写实电影感全身正面角色参考图，单一人物、静止站姿、表情中性平静、"
            "五官与服装细节清晰无遮挡，影棚均匀柔光，干净纯色背景，"
            "与场景背景图保持同一写实风格，无文字水印。"
        ),
    }
