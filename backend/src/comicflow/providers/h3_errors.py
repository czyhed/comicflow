"""Safe response-boundary diagnostics; never include upstream content."""

import logging
import re
from typing import Literal

import httpx

from comicflow.domain.models import JsonObject

H3_MAX_PROMPT_CHARACTERS = 7000


class H3PromptLengthError(RuntimeError):
    def __init__(self, characters: int, *, text_expansion_attempted: bool) -> None:
        super().__init__('VIDEO_PROMPT_TOO_LONG')
        self.detail: JsonObject = {
            'stage': 'h3_prompt', 'promptCharacters': characters,
            'maxCharacters': H3_MAX_PROMPT_CHARACTERS,
            'textExpansionAttempted': text_expansion_attempted,
        }
        logging.getLogger(__name__).warning(
            'H3 prompt budget exceeded: characters=%s limit=%s text_expansion_attempted=%s',
            characters, H3_MAX_PROMPT_CHARACTERS, text_expansion_attempted,
        )


ResponseStage = Literal['h3_text', 'h3_submit', 'h3_poll', 'h3_result']
ResponseReason = Literal[
    'message_missing', 'output_truncated', 'invalid_json', 'invalid_response',
    'invalid_envelope', 'empty_content', 'reasoning_only', 'content_refused', 'content_not_text',
    # The task existed and kept reporting progress, but never reached a terminal
    # state inside the request's time budget.
    'timeout',
    # Every poll answered with a status token we do not classify. The task may
    # still be alive upstream, which is exactly why the token itself is reported.
    'unknown_status',
]


def _business_status(body: JsonObject) -> int:
    error = body.get('error')
    raw = error.get('http_code') if isinstance(error, dict) else None
    try:
        status = (
            int(raw) if isinstance(raw, (str, int, float)) and not isinstance(raw, bool) else 400
        )
    except (TypeError, ValueError):
        status = 400
    return status if 400 <= status <= 599 else 400


def _provider_code(status: int) -> tuple[str, str]:
    if status == 401:
        return 'PROVIDER_AUTH_FAILED', 'authentication'
    if status == 403:
        return 'PROVIDER_AUTH_FAILED', 'permission_denied'
    if status == 402:
        return 'VIDEO_QUOTA_EXHAUSTED', 'quota_exhausted'
    if status == 429:
        return 'VIDEO_RATE_LIMITED', 'rate_limited'
    if status >= 500:
        return 'PROVIDER_HTTP_ERROR', 'service_error'
    return 'VIDEO_REQUEST_INVALID', 'business_rejected'


class H3BusinessError(RuntimeError):
    """A gateway rejection delivered in a nominal HTTP 200 response."""

    def __init__(
        self, body: JsonObject, stage: ResponseStage, task_id: str | None = None,
    ) -> None:
        status = _business_status(body)
        code, reason = _provider_code(status)
        error = body.get('error')
        raw_code = error.get('type') if isinstance(error, dict) else body.get('RetCode')
        upstream_code = str(raw_code)[:64]
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', upstream_code):
            upstream_code = 'unclassified'
        super().__init__(code)
        self.detail: JsonObject = {
            'stage': stage, 'reason': reason, 'upstreamStatus': status,
            'upstreamCode': upstream_code,
        }
        if task_id and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id):
            self.detail['taskId'] = task_id
        logging.getLogger(__name__).warning(
            'H3 business response rejected: stage=%s upstream_status=%s upstream_code=%s',
            stage, status, upstream_code,
        )

    @staticmethod
    def matches(body: object) -> bool:
        if not isinstance(body, dict):
            return False
        error = body.get('error')
        return (
            body.get('type') == 'error' and isinstance(error, dict)
        ) or (
            isinstance(body.get('RetCode'), (int, str))
            and str(body.get('RetCode')) not in {'', '0'}
        )


class H3ResponseError(RuntimeError):
    def __init__(
        self, stage: ResponseStage, reason: ResponseReason = 'invalid_response',
        task_id: str | None = None,
    ) -> None:
        super().__init__('PROVIDER_RESPONSE_INVALID')
        self.stage, self.reason = stage, reason
        self.task_id = (
            task_id if task_id and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id) else None
        )
        self.detail: JsonObject = {'stage': stage, 'reason': reason}
        if self.task_id:
            self.detail['taskId'] = self.task_id
        logging.getLogger(__name__).warning(
            'H3 response rejected: stage=%s reason=%s task_id=%s',
            stage, reason, self.task_id or 'unavailable',
        )


class H3TaskError(RuntimeError):
    """A known task reached a terminal non-success state, not an HTTP outage."""

    def __init__(self, status: str, task_id: str) -> None:
        cancelled = status in {'cancelled', 'canceled'}
        super().__init__('VIDEO_TASK_CANCELLED' if cancelled else 'VIDEO_GENERATION_FAILED')
        self.detail: JsonObject = {
            'stage': 'h3_poll',
            'reason': 'task_cancelled' if cancelled else 'task_failed',
            'taskStatus': 'cancelled' if cancelled else 'failed',
        }
        if re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id):
            self.detail['taskId'] = task_id
        logging.getLogger(__name__).warning(
            'H3 task ended: stage=h3_poll status=%s task_id=%s',
            self.detail['taskStatus'], self.detail.get('taskId', 'unavailable'),
        )


class H3TextResponseError(H3ResponseError):
    """Text response shape diagnostics without retaining either kind of model text."""

    def __init__(
        self, reason: ResponseReason, *, finish_reason: object = None,
        content_characters: int = 0,
    ) -> None:
        super().__init__('h3_text', reason)
        finish = finish_reason if isinstance(finish_reason, str) and finish_reason in {
            'stop', 'length', 'content_filter', 'tool_calls', 'function_call',
        } else 'unknown'
        self.detail.update(finishReason=finish, contentCharacters=content_characters)
        logging.getLogger(__name__).warning(
            'H3 text response shape: reason=%s finish_reason=%s content_characters=%s',
            reason, finish, content_characters,
        )


class H3RequestError(RuntimeError):
    """HTTP/transport failure with bounded metadata, never upstream content."""

    def __init__(
        self, error: httpx.HTTPError, stage: ResponseStage, task_id: str | None = None,
    ) -> None:
        code, reason = 'PROVIDER_HTTP_ERROR', 'connection_error'
        status = None
        if isinstance(error, httpx.TimeoutException):
            code, reason = 'PROVIDER_TIMEOUT', 'timeout'
        elif isinstance(error, httpx.HTTPStatusError):
            status = error.response.status_code
            code, reason = _provider_code(status)
            if status == 404:
                reason = 'endpoint_not_found'
            elif 400 <= status < 500 and reason == 'business_rejected':
                reason = 'request_rejected'
        super().__init__(code)
        self.detail: JsonObject = {'stage': stage, 'reason': reason}
        if status is not None:
            self.detail['upstreamStatus'] = status
        if task_id and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id):
            self.detail['taskId'] = task_id
        logging.getLogger(__name__).warning(
            'H3 request failed: stage=%s reason=%s upstream_status=%s task_id=%s',
            stage, reason, status, self.detail.get('taskId', 'unavailable'),
        )
