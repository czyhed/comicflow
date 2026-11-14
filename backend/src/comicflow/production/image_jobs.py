"""Persist image submissions independently from HTTP waits and character edits."""

from __future__ import annotations

import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject
from comicflow.infrastructure.image_jobs import TERMINAL, ImageJobStore, inputs, matches
from comicflow.production.character_assets import CharacterAssets, character_reference_request
from comicflow.production.character_boards import require_board_size, validate_board_bytes
from comicflow.production.reference_images import (
    normalize_reference_image,
    reference_asset_is_current,
)
from comicflow.production.video_jobs import freeze, refresh_images
from comicflow.production.visual_preflight import adapter_identity, digest
from comicflow.providers.drama_skills import prepare_visual_asset_request
from comicflow.providers.error_mapping import map_provider_error
from comicflow.providers.image_checkpoints import ImageTaskError, image_error_detail
from comicflow.providers.openai_image import OpenAIImageProvider
from comicflow.providers.wanx_image import BailianImageProvider

VIEWS = (("front", "正面"), ("three-quarter", "三分之四侧面"), ("profile", "侧面"))
REJECTED = {
    "PROVIDER_AUTH_FAILED",
    "IMAGE_REQUEST_INVALID",
    "IMAGE_RATE_LIMITED",
    "IMAGE_QUOTA_EXHAUSTED",
    "IMAGE_CONTENT_REJECTED",
}


def selected_provider(provider: Any, purpose: str) -> Any:
    if hasattr(provider, "selection"):
        return provider.selection.provider(
            "image-edit" if purpose in {"views", "board"} else "image", provider.fallback
        )
    return provider


def signature(provider: Any) -> str:
    return digest(
        {
            **adapter_identity(provider),
            "size": getattr(provider, "_size", None),
            "protocol": getattr(provider, "_image_protocol", None),
            "template": getattr(getattr(provider, "_transport", None), "config", None),
        }
    )


def public_job(job: JsonObject) -> JsonObject:
    result = {
        key: deepcopy(job.get(key))
        for key in (
            "id",
            "projectId",
            "characterId",
            "purpose",
            "status",
            "taskId",
            "currentStep",
            "createdAt",
            "updatedAt",
            "callsStarted",
            "attempts",
            "error",
            "errorDetail",
            "modelConfigRevision",
            "applied",
        )
    }
    expired = job.get("leaseUntil", 0) <= time.time()
    if expired and job["status"] == "submitting" and not job.get("taskId"):
        result.update(status="unknown", error="IMAGE_SUBMISSION_UNKNOWN")
    result["completedSteps"] = list(job.get("results", {}))
    result["canRecover"] = (
        expired
        and result["status"] not in TERMINAL | {"unknown"}
        and (
            bool(job.get("taskId") or job.get("providerAsset"))
            or job["status"] in {"queued", "preparing", "recoverable", "composing"}
        )
    )
    return result


class ImageJobs:
    def __init__(
        self,
        *,
        store: ImageJobStore,
        characters: CharacterAssets,
        repository: Any,
        character_repository: Any,
        provider: Any,
        asset_store: Any,
        model_config_revision: int,
    ) -> None:
        self.store, self.characters = store, characters
        self.repository, self.character_repository = repository, character_repository
        self.provider, self.asset_store = provider, asset_store
        self.model_config_revision = model_config_revision

    async def require(self, project_id: str, job_id: str) -> JsonObject:
        job = await self.store.get(job_id)
        if job is None or job["projectId"] != project_id:
            raise DomainError("IMAGE_JOB_NOT_FOUND")
        return job

    async def public(self, job: JsonObject) -> JsonObject:
        result = public_job(job)
        result["assets"] = []
        for step, asset in job.get("results", {}).items():
            url = None
            try:
                if asset.get("objectKey") and self.asset_store:
                    url = await self.characters._presigned_url_cached(asset["objectKey"])
                elif isinstance(asset.get("url"), str):
                    url = asset["url"]
            except Exception:
                pass  # A storage outage must not hide the submission journal.
            result["assets"].append({"id": asset.get("id"), "step": step, "url": url})
        return result

    async def request(
        self,
        project_id: str,
        character_id: str,
        *,
        expected_version: int,
        operation_id: str,
        purpose: str = "candidate",
        force: bool = False,
    ) -> JsonObject:
        key = digest([project_id, character_id, operation_id])
        prior = await self.store.operation(project_id, key)
        if prior:
            return prior
        if purpose not in {"candidate", "views", "board", "text-board"}:
            raise DomainError("IMAGE_JOB_PURPOSE_INVALID")
        record = await self.repository.get(project_id)
        if record is None:
            raise DomainError("PROJECT_NOT_FOUND")
        if record.project["version"] != expected_version:
            raise DomainError("VERSION_CONFLICT")
        character = await self.character_repository.get(character_id)
        if not character or character.get("projectId") != project_id:
            raise DomainError("CHARACTER_ACCESS_DENIED")
        if not character.get("appearance") or not character.get("clothing"):
            raise DomainError("CHARACTER_FIELDS_REQUIRED")
        if purpose == "views" and (
            character.get("referenceImageStatus")
            not in {"approved", "views-partial", "views-ready"}
            or not (character.get("referenceImageObjectKey") or character.get("referenceImageUrl"))
        ):
            raise DomainError("REFERENCE_IMAGE_NOT_APPROVED")
        if purpose == "board" and not (
            (character.get("referenceImageObjectKey") or character.get("referenceImageUrl"))
            and character.get("referenceImageMediaType") == "image"
        ):
            raise DomainError("REFERENCE_IMAGE_NOT_APPROVED")
        provider = selected_provider(self.provider, purpose)
        if provider is None:
            raise DomainError("REFERENCE_IMAGE_PROVIDER_REQUIRED")
        if purpose == "board":
            if not getattr(provider, "supports_image_edit", False):
                raise DomainError("IMAGE_EDIT_UNSUPPORTED")
            require_board_size(getattr(provider, "_size", ""))
        if purpose == "text-board" and getattr(provider, "_size", None):
            require_board_size(provider._size)
        job_id = f"ijob_{uuid4().hex}"
        style = deepcopy(record.project.get("visualStyleProfile"))
        if purpose == "candidate":
            requests = {
                "candidate": character_reference_request(character, f"candidate-{job_id}", style)
            }
        elif purpose == "text-board":
            requests = {"board-candidate": {
                "id": f"{project_id}_char_board_{character_id}_{job_id}",
                "imagePurpose": "character-reference-text-board",
                "styleSnapshot": style,
                "visualDescription": (
                    f"【角色】{character.get('name', '')}\n"
                    f"【外观】{character['appearance']}\n"
                    f"【服装】{character['clothing']}"
                ),
            }}
        elif purpose == "board":
            requests = {"board-candidate": {
                "id": f"{project_id}_char_board_{character_id}_{job_id}",
                "imagePurpose": "character-reference-board",
                "styleSnapshot": style,
                "visualDescription": ("基于提供的已确认主图，生成同一角色的"
                                      "一张正面、严格侧面、背面参考板。"),
                "sourceImageUrl": character.get("referenceImageUrl"),
                "sourceImageObjectKey": character.get("referenceImageObjectKey"),
            }}
        else:
            prompt = character.get("referenceImagePrompt") or (
                f"{character.get('appearance', '')}，{character.get('clothing', '')}。"
            )
            requests = {
                view: {
                    "id": f"{project_id}_char_view_{character_id}_{view}_{job_id}",
                    "imagePurpose": "character-reference-view",
                    "styleSnapshot": style,
                    "visualDescription": (
                        f"{prompt}。基于已确认的角色参考图，生成{label}视角角色参考图。"
                        "保持同一张脸、发型、体型、服装、颜色、年龄和画风，纯色背景，"
                        "只改变观察角度，不新增人物，不添加文字或水印。"
                    ),
                    "view": view,
                    "sourceImageUrl": character.get("referenceImageUrl"),
                    "sourceImageObjectKey": character.get("referenceImageObjectKey"),
                }
                for view, label in VIEWS
            }
        results = {
            v["view"]: deepcopy(v)
            for v in character.get("referenceViews", [])
            if purpose == "views" and not force and reference_asset_is_current(character, v)
        }
        frozen = {k: freeze(prepare_visual_asset_request(v)) for k, v in requests.items()}
        now = datetime.now(UTC).isoformat()
        job: JsonObject = {
            "id": job_id,
            "projectId": project_id,
            "characterId": character_id,
            "operationKey": key,
            "slot": digest([project_id, character_id]),
            "purpose": purpose,
            "characterInput": inputs(character),
            "styleSnapshot": style,
            "fingerprint": digest([inputs(character), style, purpose, force, signature(provider)]),
            "requests": frozen,
            "results": results,
            "status": "queued",
            "modelConfigRevision": self.model_config_revision,
            "configSignature": signature(provider),
            "createdAt": now,
            "updatedAt": now,
            "history": [],
            "callsStarted": 0,
            "attempts": 0,
            "leaseToken": None,
            "leaseUntil": 0,
            "leaseSeconds": max(900, 3 * float(getattr(provider, "_timeout", 600)) + 120),
        }
        return await self.store.create(job)

    async def run(self, job_id: str) -> JsonObject:
        token = uuid4().hex
        job = await self.store.claim(job_id, token)
        if job is None:
            found = await self.store.get(job_id)
            if found is None:
                raise DomainError("IMAGE_JOB_NOT_FOUND")
            return found

        async def checkpoint(status: str, fields: JsonObject | None = None) -> None:
            nonlocal job
            job = await self.store.checkpoint(job_id, token, status, fields)

        try:
            provider = selected_provider(self.provider, job["purpose"])
            for step, shot in job["requests"].items():
                if step in job["results"]:
                    continue
                if not job.get("providerAsset"):
                    if signature(provider) != job["configSignature"]:
                        raise DomainError("IMAGE_JOB_CONFIG_CHANGED")
                    if not job.get("taskId"):
                        current = await self.character_repository.get(job["characterId"])
                        record = await self.repository.get(job["projectId"])
                        if not current or not record or not matches(job, current, record.project):
                            raise DomainError("IMAGE_JOB_INPUT_CHANGED")
                        await checkpoint("preparing", {"currentStep": step})
                    prepared = (
                        shot if job.get("taskId") else await refresh_images(shot, self.asset_store)
                    )
                    if isinstance(provider, (BailianImageProvider, OpenAIImageProvider)):
                        asset = await provider.generate(
                            prepared, [], checkpoint=checkpoint, resume=job
                        )
                    else:
                        await checkpoint("submitting")
                        asset = await provider.generate(prepared, [])
                    if asset.get("dataUri"):
                        raise RuntimeError("REFERENCE_STORAGE_UNAVAILABLE")
                    await checkpoint("finalizing", {"providerAsset": asset, "currentStep": step})
                ref = await normalize_reference_image(
                    shot,
                    job["providerAsset"],
                    asset_store=self.asset_store,
                    presign=self.characters._presigned_url_cached,
                )
                if step == "candidate":
                    ref.update(
                        id=shot["id"],
                        status="candidate",
                        characterRevision=job["characterInput"].get("revision") or 0,
                    )
                elif step == "board-candidate":
                    ref.update(await validate_board_bytes(ref, self.asset_store))
                    source = job["characterInput"]
                    ref.update(
                        id=shot["id"], status="candidate", generationMode="single-edit-board",
                        layout=["front", "profile", "back"], columns=3,
                        sourceReferenceId=source.get("referenceImageObjectKey")
                        or source.get("referenceImageUrl"),
                        sourceAppearance=source.get("appearance"),
                        sourceClothing=source.get("clothing"),
                        styleSnapshot=deepcopy(job.get("styleSnapshot")),
                    )
                    if source.get("referenceImageVersion"):
                        ref["sourceImageVersion"] = source["referenceImageVersion"]
                    if job["purpose"] == "text-board":
                        ref.update(generationMode="single-text-board",
                                   layout=["face", "front", "profile", "back"], columns=4)
                        ref.pop("sourceReferenceId", None)
                        ref.pop("sourceImageVersion", None)
                else:
                    source = job["characterInput"]
                    ref.update(
                        id=f"{job['characterId']}-view-{step}",
                        view=step,
                        viewLabel=dict(VIEWS)[step],
                        status="approved",
                        sourceReferenceId=source.get("referenceImageObjectKey")
                        or source.get("referenceImageUrl"),
                    )
                    if source.get("referenceImageVersion"):
                        ref["sourceImageVersion"] = source["referenceImageVersion"]
                job = await self.store.install(
                    job_id, token, step, ref, final=step in {"candidate", "board-candidate"})
                if job["status"] in TERMINAL:
                    return job
            await checkpoint("composing")
            current = await self.character_repository.get(job["characterId"])
            record = await self.repository.get(job["projectId"])
            if not current or not record or not matches(job, current, record.project):
                raise DomainError("IMAGE_JOB_INPUT_CHANGED")
            board = current.get("referenceBoard")
            if (
                job["callsStarted"] == 0
                and board
                and board.get("columns") == 2
                and reference_asset_is_current(current, board)
            ):
                await checkpoint(
                    "succeeded",
                    {
                        "applied": True,
                        "result": {
                            "character": current,
                            "views": current.get("referenceViews", []),
                            "projectVersion": record.project["version"],
                            "reused": True,
                        },
                    },
                )
            else:
                board = await self.characters._compose_character_reference_board(
                    current, job["projectId"], job["characterId"]
                )
                if board:
                    job = await self.store.install(job_id, token, "board", board, final=True)
                else:
                    if callable(getattr(self.asset_store, "get_bytes", None)):
                        raise DomainError("REFERENCE_BOARD_FAILED")
                    # Providers without a downloadable store still expose their saved views.
                    await checkpoint(
                        "succeeded",
                        {
                            "applied": True,
                            "result": {
                                "character": current,
                                "views": current.get("referenceViews", []),
                                "projectVersion": record.project["version"],
                                "reused": not job["callsStarted"],
                            },
                        },
                    )
            return job
        except Exception as error:
            if isinstance(error, DomainError) and error.code == "IMAGE_JOB_LEASE_LOST":
                raise
            code = (
                error.code
                if isinstance(error, DomainError)
                else (
                    map_provider_error(str(error))
                    if isinstance(error, RuntimeError)
                    else "IMAGE_JOB_EXECUTION_FAILED"
                )
            )
            if job.get("taskId") or job.get("providerAsset"):
                status = (
                    "failed"
                    if isinstance(error, ImageTaskError)
                    or (job.get("providerAsset") and code == "REFERENCE_IMAGE_INVALID")
                    else "recoverable"
                )
            elif job["status"] == "submitting":
                status = "failed" if str(error) in REJECTED else "unknown"
            else:
                status = "recoverable" if code == "REFERENCE_BOARD_FAILED" else "failed"
            return await self.store.checkpoint(job_id, token, status, {
                "error": code, "errorDetail": image_error_detail(error, job['status']),
            })

    async def recover(self, project_id: str, job_id: str) -> JsonObject:
        await self.require(project_id, job_id)
        return await self.store.recover(job_id)
