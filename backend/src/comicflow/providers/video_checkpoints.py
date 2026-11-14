from collections.abc import Awaitable, Callable

from comicflow.domain.models import JsonObject

Checkpoint = Callable[[str, JsonObject | None], Awaitable[None]]


class VideoStageError(RuntimeError):
    def __init__(self, code: str, stage: str, *, status: int | None = None,
                 terminal: bool = False) -> None:
        super().__init__(code)
        self.detail: JsonObject = {'stage': stage}
        if status:
            self.detail['upstreamStatus'] = status
        self.terminal = terminal


async def report(checkpoint: Checkpoint | None, status: str,
                 fields: JsonObject | None = None) -> None:
    if checkpoint is not None:
        await checkpoint(status, fields)
