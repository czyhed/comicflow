from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from comicflow.providers.character_prompt import character_prompt_fields

ModelIdentifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    input_type: Literal["idea", "story"] = Field(alias="inputType")
    story: str
    duration_sec: int = Field(alias="durationSec")
    mode: Literal["guided", "automatic", "import_story", "import_script"]
    style_preset_id: str | None = Field(default=None, alias='stylePresetId', max_length=80)


class VersionedRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    expected_version: int = Field(alias="expectedVersion")


class VisualGenerationRequest(VersionedRequest):
    preflight_fingerprint: str | None = Field(default=None, alias='preflightFingerprint',
                                               min_length=64, max_length=64)


class VideoJobRequest(VisualGenerationRequest):
    operation_id: str = Field(alias='operationId', min_length=1, max_length=128)
    continuity_mode: Literal['auto', 'previous-tail'] = Field(
        default='auto', alias='continuityMode')


class VideoPreflightRequest(VersionedRequest):
    continuity_mode: Literal['auto', 'previous-tail'] = Field(
        default='auto', alias='continuityMode')


class VideoJobRecoveryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    task_id: str | None = Field(default=None, alias='taskId', pattern=r'^[A-Za-z0-9_-]{1,128}$')


class CharacterReferenceCandidateApprovalRequest(VersionedRequest):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    candidate_id: str = Field(alias="candidateId", min_length=1)


class CharacterReferenceViewsRequest(VersionedRequest):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    force: bool = False


class ImageJobRequest(CharacterReferenceViewsRequest):
    operation_id: str = Field(alias='operationId', min_length=1, max_length=128)
    purpose: Literal['candidate', 'views', 'board', 'text-board'] = 'candidate'


class RegenerationRequest(VersionedRequest):
    scope: Literal["visual", "audio", "lipsync", "shot"]


class CharacterPromptFields(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100)
    appearance: str = Field(default="", max_length=2000)
    clothing: str = Field(default="", max_length=2000)
    personality: str = Field(default="", max_length=2000)
    reference_image_prompt: str = Field(default="", alias="referenceImagePrompt", max_length=4000)


class CharacterPromptPreviewRequest(VersionedRequest):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    character_id: str | None = Field(default=None, alias="characterId")
    expected_revision: int = Field(default=0, alias="expectedRevision", ge=0)
    fields: CharacterPromptFields
    instructions: str = Field(default="", max_length=2000)
    purpose: Literal['full', 'settings', 'reference-image'] = 'full'
    output_fields: list[str] | None = Field(default=None, alias='outputFields')

    @model_validator(mode='after')
    def validate_output_fields(self) -> 'CharacterPromptPreviewRequest':
        character_prompt_fields(self.purpose, self.output_fields)
        return self


class ScriptUpdateRequest(VersionedRequest):
    script: dict[str, Any]


class GuidedAnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=400)


class StoryTextUpdateRequest(VersionedRequest):
    story_text: str = Field(alias="storyText", min_length=1, max_length=8000)


class ShotCreateRequest(VersionedRequest):
    shot: dict[str, Any]


class ShotOrderRequest(VersionedRequest):
    model_config = ConfigDict(populate_by_name=True)

    shot_ids: list[str] = Field(alias="shotIds")


class ShotCharactersRequest(VersionedRequest):
    model_config = ConfigDict(populate_by_name=True)

    character_ids: list[str] = Field(alias="characterIds")


class ShotTrim(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra='forbid')
    in_sec: float = Field(alias='inSec', ge=0, allow_inf_nan=False, strict=True)
    out_sec: float = Field(alias='outSec', gt=0, allow_inf_nan=False, strict=True)

    @model_validator(mode='after')
    def ordered(self) -> 'ShotTrim':
        if self.out_sec <= self.in_sec:
            raise ValueError('outSec must be greater than inSec')
        return self


class CompositionRequest(VersionedRequest):
    model_config = ConfigDict(populate_by_name=True)

    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")
    shot_ids: list[str] | None = Field(default=None, alias="shotIds", min_length=1)
    shot_trims: dict[str, ShotTrim] | None = Field(default=None, alias='shotTrims')


class TextProviderConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: Literal["openai-compatible", "bailian", "doubao", "openrouter", "custom"]
    base_url: str = Field(alias="baseUrl", min_length=1)
    model: ModelIdentifier
    timeout_ms: int = Field(alias="timeoutMs", ge=1000, le=300000)
    enabled: bool = False
    api_key: str | None = Field(default=None, alias="apiKey", min_length=1)


class MediaProviderConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    provider: Literal[
        "bailian-image", "openai-image", "compshare-h3", "xiangongyun-h3", "bailian-video"
    ]
    base_url: str = Field(alias="baseUrl", min_length=1)
    model: ModelIdentifier
    timeout_ms: int = Field(alias="timeoutMs", ge=1000, le=900000)
    enabled: bool = False
    api_key: str | None = Field(default=None, alias="apiKey", min_length=1)
    size: str = "720*1280"
    image_protocol: Literal['auto', 'wan-v2', 'wan26-image'] = Field(
        default='auto', alias='imageProtocol',
    )
    request_path: str = Field(default='', alias='requestPath')
    status_path: str = Field(default='', alias='statusPath')
    resolution: Literal[
        '480P', '720P', '768P', '1080P', '2K', '1.0P', '0.9P',
        '0.8P', '0.7P', '0.6P', '0.5P', '0.4P',
    ] | None = None
    inference_profile: Literal[
        'turbo4_av_sol_gpu_te', 'turbo8_av_sol_gpu_te', 'quality_av_sol_gpu_te'
    ] = Field(default='turbo8_av_sol_gpu_te', alias='inferenceProfile')
    generation_type: Literal['i2v', 't2v'] = Field(default='i2v', alias='generationType')
    h3_prompt_mode: Literal['local-skill', 'context-ir'] = Field(
        default='local-skill', alias='h3PromptMode'
    )
    submit_path: str = Field(default="/minimax/v2/video_generation", alias="submitPath")
    query_path: str = Field(
        default="/minimax/v2/query/video_generation/{task_id}", alias="queryPath"
    )
