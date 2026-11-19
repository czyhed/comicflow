"""Request identity supplied by the ShiploadAI gateway.

The gateway authenticates the browser session and injects ``X-Control-User-Id``
(and ``X-Control-Username``) after stripping any client-supplied copy. Values are
URL encoded by the workbench, so they must be decoded before use.

``X-User-Id`` is a legacy ComicFlow header. It is honoured only when the process
is explicitly started in development mode; production must never trust a header
the browser can set itself.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

from fastapi import Request

CONTROL_USER_ID_HEADER = "X-Control-User-Id"
CONTROL_USERNAME_HEADER = "X-Control-Username"
LEGACY_USER_ID_HEADER = "X-User-Id"

# Explicit opt-in for local development without the gateway. Never enable this
# in a deployment that sits behind the gateway.
DEV_TRUST_LEGACY_HEADER_ENV = "COMICFLOW_DEV_TRUST_X_USER_ID"
_MAX_IDENTITY_LENGTH = 256

IdentitySource = Literal["gateway", "dev-header", "anonymous"]


@dataclass(frozen=True, slots=True)
class RequestIdentity:
    """The identity a request is allowed to act as."""

    user_id: str | None
    username: str | None
    source: IdentitySource


def decode_identity_value(value: str | None) -> str | None:
    """Decode one gateway identity header and reject unusable values."""
    if value is None:
        return None
    decoded = unquote(value).strip()
    if not decoded or len(decoded) > _MAX_IDENTITY_LENGTH:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in decoded):
        return None
    return decoded


def dev_legacy_header_trusted() -> bool:
    """Whether the legacy ``X-User-Id`` header may stand in for gateway identity."""
    return os.getenv(DEV_TRUST_LEGACY_HEADER_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def resolve_identity(headers: Mapping[str, str]) -> RequestIdentity:
    """Resolve the request identity, preferring the gateway over the legacy header."""
    gateway_user_id = decode_identity_value(headers.get(CONTROL_USER_ID_HEADER))
    if gateway_user_id is not None:
        return RequestIdentity(
            user_id=gateway_user_id,
            username=decode_identity_value(headers.get(CONTROL_USERNAME_HEADER)),
            source="gateway",
        )
    if dev_legacy_header_trusted():
        legacy_user_id = decode_identity_value(headers.get(LEGACY_USER_ID_HEADER))
        if legacy_user_id is not None:
            return RequestIdentity(user_id=legacy_user_id, username=None, source="dev-header")
    return RequestIdentity(user_id=None, username=None, source="anonymous")


def identity_from_request(request: Request) -> RequestIdentity:
    cached = getattr(request.state, "comicflow_identity", None)
    if isinstance(cached, RequestIdentity):
        return cached
    identity = resolve_identity(request.headers)
    request.state.comicflow_identity = identity
    return identity


def current_identity(request: Request) -> RequestIdentity:
    """FastAPI dependency returning the full resolved identity."""
    return identity_from_request(request)


def current_user_id(request: Request) -> str | None:
    """FastAPI dependency returning the decoded user id, if the request has one."""
    return identity_from_request(request).user_id
