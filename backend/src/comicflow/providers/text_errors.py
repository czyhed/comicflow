"""Closed-set diagnostics for rejected text requests; never retain response text.

Every stage that calls a text Adapter faces the same refusal shapes, so the
stage is a parameter rather than a hardcoded story-only constant. The reason is
always taken from a closed set: an unrecognised upstream code collapses to the
status-derived reason instead of being echoed.
"""

import json
import logging
from typing import Literal

import httpx

from comicflow.domain.models import JsonObject
from comicflow.providers.message_contract import ScriptContractError

_REASONS = {
    'InvalidParameter': 'invalid_parameter',
    'InvalidParameterValue': 'invalid_parameter',
    'invalid_parameter': 'invalid_parameter',
    'InvalidEndpointOrModel.NotFound': 'model_or_endpoint_not_found',
    'ModelNotFound': 'model_or_endpoint_not_found',
    'model_not_found': 'model_or_endpoint_not_found',
    'ModelNotOpen': 'model_not_enabled',
    'InvalidApiKey': 'authentication',
    'AuthenticationError': 'authentication',
}
_PARAMETERS = {'model', 'response_format', 'stream', 'messages', 'max_tokens', 'thinking'}


class TextRequestError(RuntimeError):
    """A text refusal that keeps a bounded, closed-set reason for the caller.

    ``str(error)`` stays the provider code, so existing code that translates a
    bare code into a domain code keeps working; the detail is additive.
    """

    def __init__(self, code: str, detail: JsonObject) -> None:
        super().__init__(code)
        self.detail = detail


def script_response_error(reason: Literal[
    'message_missing', 'output_truncated', 'reasoning_only', 'empty_content',
    'content_not_text', 'content_refused', 'invalid_json', 'invalid_envelope',
    'script_contract_invalid',
], *, error: ScriptContractError | None = None) -> TextRequestError:
    """Log only a closed-set classification, never story text or upstream values."""
    detail: JsonObject = {
        'stage': 'script_split', 'reason': reason,
    }
    if error is not None:
        detail['validation'] = error.validation
    logging.getLogger(__name__).warning(
        'script_response_failure reason=%s validation=%s', reason, detail.get('validation', {}),
    )
    return TextRequestError('PROVIDER_RESPONSE_INVALID', detail)


async def text_request_error(
    response: httpx.Response, code: str, *, stage: str = 'story_text',
) -> TextRequestError:
    status = response.status_code
    reason = (
        'authentication' if status == 401 else 'permission_denied' if status == 403
        else 'rate_limited' if status == 429 else 'service_error' if status >= 500
        else 'request_rejected'
    )
    detail: JsonObject = {
        'stage': stage, 'upstreamStatus': status, 'reason': reason,
    }
    try:
        content = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            content.extend(chunk)
            if len(content) > 16384:
                return TextRequestError(code, detail)
        body = json.loads(content)
        error = body.get('error', body) if isinstance(body, dict) else {}
        if isinstance(error, dict):
            token, parameter = error.get('code'), error.get('param')
            if isinstance(token, str) and token in _REASONS:
                detail['reason'] = _REASONS[token]
            if isinstance(parameter, str) and parameter in _PARAMETERS:
                detail['parameter'] = parameter
    except (ValueError, httpx.HTTPError):
        pass  # The HTTP status remains useful if the error body is unreadable.
    return TextRequestError(code, detail)


def text_timeout_error(
    code: str, *, stage: str, timeout_ms: float | None = None,
) -> TextRequestError:
    """A request that ran out of time; report the stage and the budget it had.

    Without the budget the caller cannot tell an oversized prompt from a stalled
    upstream, and has no idea which setting to raise.
    """
    detail: JsonObject = {'stage': stage, 'reason': 'timeout'}
    if isinstance(timeout_ms, (int, float)) and not isinstance(timeout_ms, bool):
        budget = int(timeout_ms)
        if 0 < budget <= 3_600_000:
            detail['timeoutMs'] = budget
    return TextRequestError(code, detail)
