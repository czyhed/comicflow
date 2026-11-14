"""Catalog CRUD is offline; only the explicit connection test can contact a model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from comicflow.domain.errors import DomainError
from comicflow.providers.model_connection_test import check_connection
from comicflow.providers.model_protocols import (
    PROTOCOLS,
    TemplateTransport,
    validate_config,
    validate_endpoint,
)
from comicflow.providers.model_registry import ModelRegistry
from comicflow.providers.runtime_config import ProviderConfigStore


def registry_router(registry: ModelRegistry, legacy: ProviderConfigStore) -> APIRouter:
    router = APIRouter(prefix="/api/model-registry")
    testing: set[str] = set()

    @router.post("/connections/{identifier}/test")
    async def test_connection(identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        if set(payload) - {"revision", "modelId"}:
            raise DomainError("MODEL_CONFIG_INVALID")
        value = await registry._current(payload.get("revision"))
        connection = registry._find(value["connections"], identifier)
        model_id = payload.get("modelId")
        model = None
        if model_id is not None:
            if not isinstance(model_id, str):
                raise DomainError("MODEL_CONFIG_INVALID")
            model = registry._find(value["models"], model_id)
            if model["connectionId"] != identifier:
                raise DomainError("MODEL_CONFIG_INVALID")
            secret = connection.pop("encryptedKey", "")
            connection["apiKey"] = registry.cipher.decrypt(secret) if secret else ""
        if identifier in testing:
            raise DomainError("MODEL_CONNECTION_TEST_BUSY")
        testing.add(identifier)
        try:
            result = await check_connection(connection, model)
            return {**result, "revision": value["revision"]}
        finally:
            testing.discard(identifier)

    @router.get("")
    async def catalog() -> dict[str, Any]:
        return await registry.view()

    # Explicit paths avoid accepting an arbitrary collection name.
    @router.post("/connections")
    async def create_connection(payload: dict[str, Any]) -> dict[str, Any]:
        return await registry.mutate("connection", None, payload)

    @router.put("/connections/{identifier}")
    async def update_connection(identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await registry.mutate("connection", identifier, payload)

    @router.delete("/connections/{identifier}")
    async def delete_connection(identifier: str, revision: int) -> dict[str, Any]:
        return await registry.delete("connection", identifier, revision)

    @router.post("/models")
    async def create_model(payload: dict[str, Any]) -> dict[str, Any]:
        return await registry.mutate("model", None, payload)

    @router.put("/models/{identifier}")
    async def update_model(identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await registry.mutate("model", identifier, payload)

    @router.delete("/models/{identifier}")
    async def delete_model(identifier: str, revision: int) -> dict[str, Any]:
        return await registry.delete("model", identifier, revision)

    @router.put("/bindings")
    async def bindings(payload: dict[str, Any]) -> dict[str, Any]:
        return await registry.bind(payload)

    @router.post("/models/{identifier}/preview")
    async def preview(identifier: str) -> dict[str, Any]:
        view = await registry.view()
        model = registry._find(view["models"], identifier)
        connection = registry._find(view["connections"], model["connectionId"])
        config = validate_config(model['protocol'], model["config"])
        validate_endpoint(model['protocol'], connection['baseUrl'])
        body = {
            "model": model["model"],
            "messages": [
                {"role": "system", "content": "<由当前阶段 Skill/契约生成>"},
                {"role": "user", "content": "<当前故事、镜头或角色输入>"},
            ],
        }
        if model["protocol"] in {"chat-completions", "doubao-chat", "chat-image"}:
            transport = TemplateTransport(config, connection["baseUrl"], "<服务端密钥>")
            try:
                return {
                    "kind": "request-template",
                    "networkCalled": False,
                    "url": connection["baseUrl"]
                    + config.get("request", {}).get("path", "/chat/completions"),
                    "body": transport.payload(body),
                    "headers": {"Authorization": "<服务端注入，不返回密钥>"},
                    "responseTextPath": config.get(
                        "responseTextPath", "choices[0].message.content"
                    ),
                }
            finally:
                await transport.aclose()
        return {
            "kind": "adapter-settings",
            "networkCalled": False,
            "model": model["model"],
            "protocol": model["protocol"],
            "baseUrl": connection["baseUrl"],
            "config": config,
            "note": "参数预览；实际参考图、时长和提示词由生成阶段校验后组装。",
        }

    @router.post("/import-legacy")
    async def import_legacy(payload: dict[str, Any]) -> dict[str, Any]:
        value = await registry._current(payload.get("revision"))
        if value["models"] or value["connections"]:
            raise DomainError("MODEL_CONFIG_IMPORT_REQUIRES_EMPTY")
        for capability in ("text", "image", "video"):
            for slot in ("test", "production"):
                old = legacy.get_profile(capability, slot)
                if not old.get("provider") or not old.get("model"):
                    continue
                mapping = {
                    "doubao": "doubao-chat",
                    "openai-image": "chat-image",
                    "bailian-video": "wan-video",
                    "compshare-h3": "compshare-h3",
                    "xiangongyun-h3": "xiangongyun-h3",
                }
                protocol = mapping.get(old["provider"], "chat-completions")
                if capability == "image" and old["provider"] == "bailian-image":
                    protocol = (
                        "wan26-image"
                        if old.get("imageProtocol") == "wan26-image"
                        or old["model"] == "wan2.6-image"
                        else "wan-image"
                    )
                cid, mid = f"import-{capability}-{slot}", f"model-{capability}-{slot}"
                value["connections"].append(
                    {
                        "id": cid,
                        "name": f"{capability} {slot}",
                        "baseUrl": old["baseUrl"],
                        "encryptedKey": registry.cipher.encrypt(old["apiKey"])
                        if old.get("apiKey")
                        else "",
                    }
                )
                config = dict(PROTOCOLS[protocol]["defaults"])
                for key in config:
                    if key in old and old[key] is not None:
                        config[key] = old[key]
                # Existing imported chat-image used /v1/chat/completions relative to base URL.
                if protocol == "chat-image":
                    config["request"] = {"path": "/v1/chat/completions"}
                config = validate_config(protocol, config)
                value["models"].append(
                    {
                        "id": mid,
                        "name": f"{old['model']} · {slot}",
                        "connectionId": cid,
                        "model": old["model"],
                        "protocol": protocol,
                        "config": config,
                        "enabled": bool(old.get("enabled")),
                    }
                )
                if (
                    legacy.active_slot(capability) == slot
                    and old.get("enabled")
                    and old.get("apiKey")
                ):
                    value["bindings"].update(dict.fromkeys(PROTOCOLS[protocol]["usages"], mid))
        return await registry._save(value)

    return router
