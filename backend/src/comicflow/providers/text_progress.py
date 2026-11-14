"""Request-scoped output observer; never starts or retries model work."""
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from comicflow.domain.models import JsonObject

text_progress: ContextVar[Callable[[JsonObject], Awaitable[None]] | None] = ContextVar(
    'text_progress', default=None,
)


async def report_text_progress(event: JsonObject) -> None:
    callback = text_progress.get()
    if callback is not None:
        await callback(event)
