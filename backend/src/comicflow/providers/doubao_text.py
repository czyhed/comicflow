"""Volcengine Ark Doubao text adapter.

Ark exposes an OpenAI-compatible Chat Completions endpoint. The shared text
provider owns ComicFlow's response normalization and H3 Skill integration;
this adapter gives the runtime an explicit provider identity and Ark defaults.
"""

from __future__ import annotations

import httpx

from comicflow.providers.bailian_text import BailianTextProvider


class DoubaoTextProvider(BailianTextProvider):
    """Use Doubao through the Volcengine Ark OpenAI-compatible API."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model: str = "Doubao-Seed-2.1-turbo",
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )

