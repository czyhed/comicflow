"""Versioned model catalog. Secrets never leave the server in catalog views."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from comicflow.domain.errors import DomainError
from comicflow.infrastructure.database import ModelRegistryRow
from comicflow.providers.model_protocols import PROTOCOLS, USAGES, invalid, validate_config


def empty_catalog() -> dict[str, Any]:
    return {"revision": 0, "connections": [], "models": [], "bindings": {}}


class RegistryRepository(Protocol):
    scope: str

    async def load(self, revision: int | None = None) -> dict[str, Any]: ...
    async def save(self, value: dict[str, Any], expected: int) -> None: ...


class MemoryRegistryRepository:
    scope = "memory"

    def __init__(self) -> None:
        self._history = [empty_catalog()]
        self._lock = asyncio.Lock()

    async def load(self, revision: int | None = None) -> dict[str, Any]:
        if revision is not None and not 0 <= revision < len(self._history):
            raise DomainError("MODEL_CONFIG_VERSION_NOT_FOUND")
        return deepcopy(self._history[-1 if revision is None else revision])

    async def save(self, value: dict[str, Any], expected: int) -> None:
        async with self._lock:
            if expected != len(self._history) - 1:
                raise DomainError("MODEL_CONFIG_CONFLICT")
            self._history.append(deepcopy(value))


class SqlRegistryRepository:
    scope = "postgresql"

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def load(self, revision: int | None = None) -> dict[str, Any]:
        if revision == 0:
            return empty_catalog()
        try:
            async with self.sessions() as session:
                query = select(ModelRegistryRow).order_by(ModelRegistryRow.revision.desc()).limit(1)
                if revision is not None:
                    query = query.where(ModelRegistryRow.revision == revision)
                row = await session.scalar(query)
                if row:
                    return deepcopy(row.payload)
                if revision is not None:
                    raise DomainError("MODEL_CONFIG_VERSION_NOT_FOUND")
                return empty_catalog()
        except SQLAlchemyError:
            raise DomainError("MODEL_CONFIG_STORAGE_UNAVAILABLE") from None

    async def save(self, value: dict[str, Any], expected: int) -> None:
        # Unique revision is the compare-and-swap; concurrent writers cannot lose updates.
        if (await self.load())["revision"] != expected:
            raise DomainError("MODEL_CONFIG_CONFLICT")
        try:
            async with self.sessions.begin() as session:
                session.add(ModelRegistryRow(revision=expected + 1, payload=deepcopy(value)))
        except IntegrityError:
            raise DomainError("MODEL_CONFIG_CONFLICT") from None
        except SQLAlchemyError:
            raise DomainError("MODEL_CONFIG_STORAGE_UNAVAILABLE") from None


class SecretCipher:
    def __init__(self, key: bytes | None = None, path: Path | None = None) -> None:
        self._key = key
        self.path = path

    @classmethod
    def ephemeral(cls) -> SecretCipher:
        return cls(Fernet.generate_key())

    @classmethod
    def configured(cls) -> SecretCipher:
        key = os.getenv("MODEL_CONFIG_ENCRYPTION_KEY")
        return cls(
            key.encode() if key else None,
            Path(os.getenv("MODEL_CONFIG_KEY_FILE", "var/config/model-config.key")),
        )

    def _fernet(self, *, create: bool = False) -> Fernet:
        try:
            if self._key is None and self.path is not None:
                if create and not self.path.exists():
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.path.with_name(f".model-key-{uuid4().hex}")
                    try:
                        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                        with os.fdopen(descriptor, "wb") as stream:
                            stream.write(Fernet.generate_key())
                        # Publish the fully written key atomically without replacing another writer.
                        os.link(temporary, self.path)
                    except FileExistsError:
                        pass
                    finally:
                        temporary.unlink(missing_ok=True)
                self._key = self.path.read_bytes().strip()
            if self._key is None:
                raise ValueError("missing key")
            return Fernet(self._key)
        except (OSError, ValueError):
            raise DomainError("MODEL_CONFIG_KEY_INVALID") from None

    def encrypt(self, value: str) -> str:
        return self._fernet(create=True).encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except (InvalidToken, ValueError):
            raise DomainError("MODEL_CONFIG_KEY_INVALID") from None


class ModelRegistry:
    def __init__(self, repository: RegistryRepository, cipher: SecretCipher) -> None:
        self.repository, self.cipher = repository, cipher

    async def view(self) -> dict[str, Any]:
        value = await self.repository.load()
        for connection in value["connections"]:
            connection["configured"] = bool(connection.pop("encryptedKey", ""))
        return {**value, "scope": self.repository.scope, "usages": USAGES, "templates": PROTOCOLS}

    async def snapshot(self, revision: int | None = None) -> dict[str, Any]:
        value = await self.repository.load(revision)
        for connection in value["connections"]:
            secret = connection.pop("encryptedKey", "")
            connection["apiKey"] = self.cipher.decrypt(secret) if secret else ""
        return value

    async def _current(self, expected: Any) -> dict[str, Any]:
        if type(expected) is not int:
            invalid()
        value = await self.repository.load()
        if value["revision"] != expected:
            raise DomainError("MODEL_CONFIG_CONFLICT")
        return value

    @staticmethod
    def _named(value: dict[str, Any], field: str, maximum: int = 200) -> str:
        text = value.get(field)
        if not isinstance(text, str) or not text.strip() or len(text) > maximum:
            invalid()
        return str(text).strip()

    @staticmethod
    def _find(items: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
        found = next((v for v in items if v["id"] == identifier), None)
        if found is None:
            raise DomainError("MODEL_CONFIG_NOT_FOUND")
        return found

    @staticmethod
    def _validate_bindings(value: dict[str, Any]) -> None:
        for usage, identifier in value["bindings"].items():
            if usage not in USAGES:
                invalid()
            model = ModelRegistry._find(value["models"], identifier)
            conn = ModelRegistry._find(value["connections"], model["connectionId"])
            if not model["enabled"] or not conn.get("encryptedKey"):
                raise DomainError("PROVIDER_NOT_CONFIGURED")
            if usage not in PROTOCOLS[model["protocol"]]["usages"]:
                raise DomainError("MODEL_CAPABILITY_UNSUPPORTED")

    async def _save(self, value: dict[str, Any]) -> dict[str, Any]:
        self._validate_bindings(value)
        expected = value["revision"]
        value["revision"] += 1
        await self.repository.save(value, expected)
        return await self.view()

    async def mutate(
        self, kind: str, identifier: str | None, payload: dict[str, Any]
    ) -> dict[str, Any]:
        from comicflow.providers.model_protocols import validate_endpoint

        value = await self._current(payload.get("revision"))
        if len(json.dumps(payload)) > 64000 or kind not in {"connection", "model"}:
            invalid()
        items = value["connections" if kind == "connection" else "models"]
        old = self._find(items, identifier) if identifier else {}
        common = {
            "id": identifier or f"{kind}_{uuid4().hex[:16]}",
            "name": self._named(payload, "name"),
        }
        if kind == "connection":
            if set(payload) - {"revision", "name", "baseUrl", "apiKey"}:
                invalid()
            url = self._named(payload, "baseUrl", 2000).rstrip("/")
            parsed = urlparse(url)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or any(character.isspace() for character in url)
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                invalid()
            key = payload.get("apiKey")
            if key is not None and (not isinstance(key, str) or not key.strip() or len(key) > 8000):
                invalid()
            previous = urlparse(old.get("baseUrl", ""))
            if key:
                existing = next(
                    (c["encryptedKey"] for c in value["connections"] if c.get("encryptedKey")), None
                )
                if existing:
                    # A lost master key must not be silently replaced while old secrets exist.
                    self.cipher.decrypt(existing)
            if (
                old.get("encryptedKey")
                and key is None
                and (parsed.scheme, parsed.netloc) != (previous.scheme, previous.netloc)
            ):
                raise DomainError("PROVIDER_CREDENTIALS_REQUIRED")
            item = {
                **common,
                "baseUrl": url,
                "encryptedKey": self.cipher.encrypt(key) if key else old.get("encryptedKey", ""),
            }
            for model in value['models']:
                if model['connectionId'] == identifier:
                    validate_endpoint(model['protocol'], url)
        else:
            if set(payload) - {
                "revision",
                "name",
                "connectionId",
                "protocol",
                "model",
                "enabled",
                "config",
            }:
                invalid()
            connection_id = self._named(payload, "connectionId")
            connection = self._find(value["connections"], connection_id)
            protocol = self._named(payload, "protocol")
            config = validate_config(protocol, payload.get("config", {}))
            validate_endpoint(protocol, connection['baseUrl'])
            if type(payload.get("enabled", False)) is not bool:
                invalid()
            item = {
                **common,
                "connectionId": connection_id,
                "protocol": protocol,
                "model": self._named(payload, "model"),
                "enabled": payload.get("enabled", False),
                "config": config,
            }
            if protocol not in {"chat-completions", "doubao-chat"}:
                from comicflow.providers.media_config import build_media_provider

                connection = self._find(value["connections"], connection_id)
                try:
                    build_media_provider(
                        "video" if "video" in PROTOCOLS[protocol]["usages"] else "image",
                        {
                            **config,
                            "provider": PROTOCOLS[protocol]["provider"],
                            "model": item["model"],
                            "baseUrl": connection["baseUrl"],
                            "enabled": True,
                            "apiKey": "validation-only-no-network",
                        },
                        None,
                    )
                except RuntimeError:
                    invalid()
        if identifier:
            items[items.index(old)] = item
        else:
            if len(items) >= 200:
                invalid()
            items.append(item)
        return await self._save(value)

    async def bind(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = await self._current(payload.get("revision"))
        if set(payload) != {"revision", "bindings"} or not isinstance(payload["bindings"], dict):
            invalid()
        value["bindings"] = {k: v for k, v in payload["bindings"].items() if v is not None}
        if any(not isinstance(v, str) for v in value["bindings"].values()):
            invalid()
        return await self._save(value)

    async def delete(self, kind: str, identifier: str, revision: int) -> dict[str, Any]:
        value = await self._current(revision)
        if kind not in {"connection", "model"}:
            invalid()
        if (
            kind == "connection"
            and any(m["connectionId"] == identifier for m in value["models"])
            or kind == "model"
            and identifier in value["bindings"].values()
        ):
            raise DomainError("MODEL_CONFIG_IN_USE")
        items = value["connections" if kind == "connection" else "models"]
        items.remove(self._find(items, identifier))
        return await self._save(value)
