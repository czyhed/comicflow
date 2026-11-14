import re
from collections.abc import Awaitable, Callable

import httpx

from comicflow.domain.models import JsonObject

Checkpoint = Callable[[str, JsonObject | None], Awaitable[None]]


class ImageTaskError(RuntimeError):
    """The provider explicitly reported a terminal task, not a query failure."""


class ImageResponseError(RuntimeError):
    """Keep only bounded diagnostic identifiers, never the response or prompt."""

    def __init__(self, code: str, status: int, body: object) -> None:
        super().__init__(code)
        self.detail: JsonObject = {'upstreamStatus': status}
        if isinstance(body, dict):
            upstream_code = body.get('code')
            request_id = body.get('request_id')
            if isinstance(upstream_code, str) and re.fullmatch(
                r'[A-Za-z][A-Za-z0-9.]{0,80}', upstream_code,
            ):
                self.detail['upstreamCode'] = upstream_code
            if isinstance(request_id, str) and re.fullmatch(r'[0-9a-fA-F-]{16,64}', request_id):
                self.detail['requestId'] = request_id


def image_error_detail(error: Exception, stage: str) -> JsonObject:
    detail: JsonObject = {'stage': stage}
    cause: BaseException | None = error
    seen: set[int] = set()
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        if isinstance(cause, ImageResponseError):
            detail.update(cause.detail)
        if isinstance(cause, httpx.RequestError):
            detail['transportError'] = type(cause).__name__
            break
        cause = cause.__cause__
    return detail


async def report(checkpoint: Checkpoint | None, status: str,
                 fields: JsonObject | None = None) -> None:
    if checkpoint is not None:
        await checkpoint(status, fields)
