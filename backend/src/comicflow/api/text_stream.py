"""Stream one operation's progress and authoritative result over its original POST."""
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from fastapi.responses import StreamingResponse

from comicflow.domain.errors import DomainError
from comicflow.domain.models import JsonObject
from comicflow.providers.text_progress import text_progress

# Keep the original operation alive on browser disconnect; never resubmit it.
_running: set[asyncio.Task[None]] = set()


async def text_response(
    accept: str | None, operation: Callable[[], Awaitable[JsonObject]],
) -> JsonObject | StreamingResponse:
    if not accept or 'text/event-stream' not in accept:
        return await operation()

    async def stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[JsonObject] = asyncio.Queue()
        attached = True

        async def emit(event: JsonObject) -> None:
            if attached:
                queue.put_nowait(event)

        async def run() -> None:
            token = text_progress.set(emit)
            try:
                await emit({'type': 'phase', 'phase': 'waiting'})
                result = await operation()
                await emit({'type': 'result', 'result': result})
            except DomainError as error:
                await emit({'type': 'error', 'error': {'error': error.code, **error.detail}})
            except Exception:
                # Never expose upstream response bodies or credentials.
                logging.getLogger(__name__).error('text_stream_operation_failed')
                await emit({'type': 'error', 'error': {'error': 'PROVIDER_UNAVAILABLE'}})
            finally:
                text_progress.reset(token)

        task = asyncio.create_task(run())
        _running.add(task)
        task.add_done_callback(_running.discard)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except TimeoutError:
                    yield ': heartbeat\n\n'
                    continue
                yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
                if event['type'] in {'result', 'error'}:
                    break
        finally:
            attached = False

    return StreamingResponse(stream(), media_type='text/event-stream', headers={
        'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
    })
