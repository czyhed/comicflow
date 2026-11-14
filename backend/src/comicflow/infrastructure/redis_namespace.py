"""One environment namespace for queues, results and temporary generation state."""

from __future__ import annotations

import os
import re


def resolve_redis_namespace(namespace: str | None = None) -> str:
    value = os.getenv("COMICFLOW_REDIS_NAMESPACE", "") if namespace is None else namespace
    if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError(
            "COMICFLOW_REDIS_NAMESPACE must contain 1-64 ASCII letters, digits, "
            "underscores or hyphens and start with a letter or digit"
        )
    return value
