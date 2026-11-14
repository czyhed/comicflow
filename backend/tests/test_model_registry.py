import json

import pytest
from comicflow.domain.errors import DomainError
from comicflow.providers.model_registry import MemoryRegistryRepository, ModelRegistry, SecretCipher


def make_registry():
    return ModelRegistry(MemoryRegistryRepository(), SecretCipher.ephemeral())


async def add_connection(registry, name="方舟"):
    return await registry.mutate(
        "connection",
        None,
        {
            "revision": (await registry.view())["revision"],
            "name": name,
            "baseUrl": "https://example.test/v3",
            "apiKey": "private-unit-test-key",
        },
    )


async def test_many_models_share_a_connection_and_bind_separate_purposes():
    registry = make_registry()
    view = await add_connection(registry)
    connection = view["connections"][0]["id"]
    for i in range(3):
        view = await registry.mutate(
            "model",
            None,
            {
                "revision": view["revision"],
                "name": f"model-{i}",
                "connectionId": connection,
                "protocol": "chat-completions",
                "model": f"custom-{i}",
                "enabled": True,
                "config": {},
            },
        )
    view = await registry.bind(
        {
            "revision": view["revision"],
            "bindings": {
                "story": view["models"][0]["id"],
                "script": view["models"][1]["id"],
            },
        }
    )
    assert len(view["models"]) == 3
    assert view["bindings"]["story"] != view["bindings"]["script"]
    assert "private-unit-test-key" not in json.dumps(view)
    assert "private-unit-test-key" not in json.dumps(await registry.repository.load())


async def test_stale_update_cannot_overwrite_other_window():
    registry = make_registry()
    await add_connection(registry)
    with pytest.raises(DomainError, match="MODEL_CONFIG_CONFLICT"):
        await registry.mutate(
            "connection",
            None,
            {
                "revision": 0,
                "name": "stale",
                "baseUrl": "https://example.test",
            },
        )


async def test_connection_keeps_key_but_refuses_sending_it_to_new_origin():
    registry = make_registry()
    view = await add_connection(registry)
    conn = view["connections"][0]
    view = await registry.mutate(
        "connection",
        conn["id"],
        {
            "revision": view["revision"],
            "name": "改名",
            "baseUrl": conn["baseUrl"],
        },
    )
    assert view["connections"][0]["configured"]
    with pytest.raises(DomainError, match="PROVIDER_CREDENTIALS_REQUIRED"):
        await registry.mutate(
            "connection",
            conn["id"],
            {
                "revision": view["revision"],
                "name": "新平台",
                "baseUrl": "https://other.test",
            },
        )


async def test_history_is_immutable_and_cipher_failure_never_falls_back():
    registry = make_registry()
    first = await add_connection(registry)
    await add_connection(registry, "另一个连接")
    historical = await registry.snapshot(first["revision"])
    assert len(historical["connections"]) == 1
    wrong_key = ModelRegistry(registry.repository, SecretCipher.ephemeral())
    with pytest.raises(DomainError, match="MODEL_CONFIG_KEY_INVALID"):
        await wrong_key.snapshot()


async def test_unknown_json_setting_is_rejected_before_any_network_call():
    registry = make_registry()
    view = await add_connection(registry)
    with pytest.raises(DomainError, match="MODEL_CONFIG_INVALID"):
        await registry.mutate(
            "model",
            None,
            {
                "revision": view["revision"],
                "name": "H3",
                "connectionId": view["connections"][0]["id"],
                "protocol": "compshare-h3",
                "model": "MiniMax-H3",
                "enabled": True,
                "config": {"resolution": "720P"},
            },
        )


async def test_database_roundtrip_and_optimistic_concurrency(tmp_path):
    import asyncio

    from comicflow.infrastructure.database import Base, create_session_factory
    from comicflow.providers.model_registry import SqlRegistryRepository

    engine, sessions = create_session_factory(f"sqlite+aiosqlite:///{tmp_path / 'models.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    key_file = tmp_path / "config" / "model-config.key"
    first = ModelRegistry(SqlRegistryRepository(sessions), SecretCipher(path=key_file))
    second = ModelRegistry(SqlRegistryRepository(sessions), SecretCipher(path=key_file))
    try:
        view = await add_connection(first)
        assert (await second.snapshot())["connections"][0]["apiKey"] == "private-unit-test-key"
        assert "private-unit-test-key" not in json.dumps(await second.repository.load())
        payload = {
            "revision": view["revision"],
            "name": "duplicate writer",
            "baseUrl": "https://example.test",
            "apiKey": "new-key",
        }
        outcomes = await asyncio.gather(
            first.mutate("connection", None, payload),
            second.mutate("connection", None, payload),
            return_exceptions=True,
        )
        assert sum(isinstance(outcome, DomainError) for outcome in outcomes) == 1
        assert (await second.view())["revision"] == 2
        assert len((await second.snapshot(1))["connections"]) == 1
    finally:
        await engine.dispose()


async def configured_model(registry, protocol="chat-completions"):
    view = await add_connection(registry)
    return await registry.mutate(
        "model",
        None,
        {
            "revision": view["revision"],
            "name": "model",
            "connectionId": view["connections"][0]["id"],
            "protocol": protocol,
            "model": "custom-model",
            "enabled": True,
            "config": {},
        },
    )


async def test_binding_capability_and_dependency_deletion_guards():
    registry = make_registry()
    view = await configured_model(registry)
    model = view["models"][0]
    with pytest.raises(DomainError, match="MODEL_CAPABILITY_UNSUPPORTED"):
        await registry.bind({"revision": view["revision"], "bindings": {"image-edit": model["id"]}})
    view = await registry.bind({"revision": view["revision"], "bindings": {"story": model["id"]}})
    with pytest.raises(DomainError, match="MODEL_CONFIG_IN_USE"):
        await registry.delete("model", model["id"], view["revision"])
    with pytest.raises(DomainError, match="MODEL_CONFIG_IN_USE"):
        await registry.delete("connection", model["connectionId"], view["revision"])
    view = await registry.bind({"revision": view["revision"], "bindings": {}})
    view = await registry.delete("model", model["id"], view["revision"])
    view = await registry.delete("connection", model["connectionId"], view["revision"])
    assert not view["connections"] and not view["models"]


async def test_requests_freeze_selection_and_new_runtime_reads_saved_bindings():
    from comicflow.infrastructure.memory import Runtime, create_memory_runtime
    from comicflow.providers.model_selection import selected_runtime

    runtime = create_memory_runtime()
    view = await configured_model(runtime.model_registry)
    model = view["models"][0]
    view = await runtime.model_registry.bind(
        {
            "revision": view["revision"],
            "bindings": {"story": model["id"], "script": model["id"]},
        }
    )
    first = await selected_runtime(runtime)
    view = await runtime.model_registry.mutate(
        "model",
        model["id"],
        {
            **{k: v for k, v in model.items() if k != "id"},
            "revision": view["revision"],
            "model": "changed-model",
        },
    )
    worker = Runtime(
        pipeline=runtime.pipeline,
        provider_config_store=runtime.provider_config_store,
        generation_state_store=runtime.generation_state_store,
        model_registry=ModelRegistry(
            runtime.model_registry.repository, runtime.model_registry.cipher
        ),
    )
    latest = await selected_runtime(worker)
    historical = await selected_runtime(worker, first.pipeline._model_config_revision)
    assert first.pipeline._text_provider.generate_story_text.__self__._model == "custom-model"
    assert historical.pipeline._text_provider.split_script.__self__._model == "custom-model"
    assert latest.pipeline._text_provider.generate_story_text.__self__._model == "changed-model"
    assert runtime.pipeline._model_config_revision == 0


async def test_api_import_preview_and_updates_never_invoke_provider(monkeypatch):
    import httpx
    from comicflow.api.app import create_app
    from comicflow.infrastructure.memory import create_memory_runtime

    def forbidden(*args, **kwargs):
        raise AssertionError("Configuration must never contact a provider")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    runtime = create_memory_runtime()
    runtime.provider_config_store.configure_text(
        {
            "provider": "doubao",
            "model": "my-model",
            "baseUrl": "https://test.invalid/v3",
            "enabled": True,
            "timeoutMs": 120000,
        },
        "private-key-not-for-response",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(runtime)), base_url="http://test"
    ) as client:
        result = await client.post("/api/model-registry/import-legacy", json={"revision": 0})
        assert result.status_code == 200
        assert "private-key-not-for-response" not in result.text
        data = result.json()
        identifier = data["models"][0]["id"]
        preview = await client.post(f"/api/model-registry/models/{identifier}/preview")
        assert preview.json()["networkCalled"] is False
        assert "private-key-not-for-response" not in preview.text
        status = (await client.get("/api/provider-config")).json()
        assert status["text"]["model"] == "my-model"
        assert status["text"]["enabled"] is True
        old_write = await client.delete("/api/provider-config/text")
        assert old_write.status_code == 409
        repeat = await client.post(
            "/api/model-registry/import-legacy", json={"revision": data["revision"]}
        )
        assert repeat.status_code == 400


def test_atomic_key_file_is_shared_by_concurrent_process_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "model.key"

    def write(_):
        return SecretCipher(path=path).encrypt("test-secret")

    with ThreadPoolExecutor(max_workers=8) as pool:
        encrypted = list(pool.map(write, range(20)))
    cipher = SecretCipher(path=path)
    assert all(cipher.decrypt(value) == "test-secret" for value in encrypted)


async def test_missing_migration_has_specific_error_and_lost_key_cannot_be_replaced(tmp_path):
    from comicflow.infrastructure.database import create_session_factory
    from comicflow.providers.model_registry import SqlRegistryRepository

    engine, sessions = create_session_factory(f"sqlite+aiosqlite:///{tmp_path / 'empty.db'}")
    try:
        with pytest.raises(DomainError, match="MODEL_CONFIG_STORAGE_UNAVAILABLE"):
            await SqlRegistryRepository(sessions).load()
    finally:
        await engine.dispose()
    registry = make_registry()
    await add_connection(registry)
    lost = ModelRegistry(registry.repository, SecretCipher(path=tmp_path / "missing.key"))
    with pytest.raises(DomainError, match="MODEL_CONFIG_KEY_INVALID"):
        await add_connection(lost)
    assert not (tmp_path / "missing.key").exists()


async def test_worker_message_carries_pinned_registry_version(monkeypatch):
    from comicflow.worker.celery_app import celery_app, publish_to_celery

    calls = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, **kwargs: calls.append((name, kwargs))
    )
    await publish_to_celery(
        "production.generation.advance",
        {
            "projectId": "project-test",
            "modelConfigRevision": 7,
        },
    )
    assert calls[0][1]["kwargs"] == {"project_id": "project-test", "model_config_revision": 7}


async def test_image_and_image_edit_use_distinct_saved_models(monkeypatch):
    from comicflow.infrastructure.memory import create_memory_runtime
    from comicflow.providers.model_selection import selected_runtime
    from comicflow.providers.wanx_image import BailianImageProvider

    calls = []

    async def generate(self, shot, characters):
        calls.append((self._model, shot.get("sourceImageUrl")))
        return {"id": "offline"}

    monkeypatch.setattr(BailianImageProvider, "generate", generate)
    runtime = create_memory_runtime()
    view = await configured_model(runtime.model_registry, "wan26-image")
    first = view["models"][0]
    view = await runtime.model_registry.mutate(
        "model",
        None,
        {
            "revision": view["revision"],
            "name": "separate-edit",
            "connectionId": first["connectionId"],
            "model": "custom-edit",
            "protocol": "wan26-image",
            "enabled": True,
            "config": {},
        },
    )
    await runtime.model_registry.bind(
        {
            "revision": view["revision"],
            "bindings": {
                "image": first["id"],
                "image-edit": view["models"][1]["id"],
            },
        }
    )
    selected = await selected_runtime(runtime)
    provider = selected.pipeline._reference_image_provider
    await provider.generate({"id": "portrait"}, [])
    await provider.generate({"id": "views", "sourceImageUrl": "https://offline.test/source"}, [])
    assert calls == [("custom-model", None), ("custom-edit", "https://offline.test/source")]


async def test_custom_template_sends_stage_skill_to_selected_model_without_retry():
    import httpx
    from comicflow.providers.model_selection import ModelSelection

    registry = make_registry()
    view = await configured_model(registry)
    model = view["models"][0]
    view = await registry.mutate(
        "model",
        model["id"],
        {
            **{k: v for k, v in model.items() if k != "id"},
            "revision": view["revision"],
            "config": {
                "request": {
                    "path": "/custom",
                    "body": {
                        "model": "{{model}}",
                        "messages": "{{messages}}",
                        "temperature": 0.25,
                    },
                }
            },
        },
    )
    await registry.bind({"revision": view["revision"], "bindings": {"video-prompt": model["id"]}})
    provider = ModelSelection(await registry.snapshot(), None).provider("video-prompt", None)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})

    provider._transport.inner = httpx.MockTransport(handler)
    result = await provider.compile_h3_prompt("Skill rules must stay here", "中文镜头输入")
    assert result == {"ok": True}
    body = json.loads(requests[0].content)
    assert body["model"] == "custom-model"
    assert body["messages"][0]["content"] == "Skill rules must stay here"
    assert body["messages"][1]["content"] == "中文镜头输入"
    assert body["temperature"] == 0.25
    assert len(requests) == 1


def test_missing_registry_migration_is_explained_on_legacy_config_write(monkeypatch):
    from comicflow.api.app import create_app
    from comicflow.infrastructure.memory import create_memory_runtime
    from fastapi.testclient import TestClient

    runtime = create_memory_runtime()

    async def unavailable(*args, **kwargs):
        raise DomainError("MODEL_CONFIG_STORAGE_UNAVAILABLE")

    monkeypatch.setattr(runtime.model_registry.repository, "load", unavailable)
    with TestClient(create_app(runtime), raise_server_exceptions=False) as client:
        response = client.post("/api/provider-config/text", json={})
    assert response.status_code == 503
    assert response.json() == {"error": "MODEL_CONFIG_STORAGE_UNAVAILABLE"}
