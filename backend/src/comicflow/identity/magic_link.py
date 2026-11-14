from __future__ import annotations

import time
from dataclasses import dataclass, field
from secrets import token_urlsafe


@dataclass(slots=True)
class MagicLinkService:
    """Single-use development magic links; replace delivery with a mail adapter in production."""

    _tokens: dict[str, str] = field(default_factory=dict)
    ttl_seconds: int = 900
    _issued_at: dict[str, float] = field(default_factory=dict)

    def issue(self, email: str) -> dict[str, str]:
        normalized = email.strip().lower()
        if "@" not in normalized:
            raise ValueError("INVALID_EMAIL")
        token = token_urlsafe(24)
        self._tokens[token] = normalized
        self._issued_at[token] = time.time()
        return {"email": normalized, "token": token}

    def verify(self, token: str) -> dict[str, str]:
        email = self._tokens.pop(token, None)
        if email is None:
            raise ValueError("INVALID_MAGIC_LINK")
        issued_at = self._issued_at.pop(token, None)
        if issued_at is None or time.time() - issued_at > self.ttl_seconds:
            raise ValueError("EXPIRED_MAGIC_LINK")
        return {"userId": f"user_{email}", "email": email}
