from __future__ import annotations

from typing import Protocol

from comicflow.domain.models import JsonObject


class EmailAdapter(Protocol):
    async def send_magic_link(
        self, recipient: str, token: str, verify_url: str
    ) -> JsonObject: ...
