"""Translation from provider-raised RuntimeError codes to domain error codes.

Provider modules signal failures by raising ``RuntimeError`` with a bare code
string. Callers must translate those into the domain codes the API maps to HTTP
statuses. That translation used to be duplicated as an inline dict at each call
site, and the copies drifted: one omitted ``PROVIDER_INVALID_RESPONSE``, so a
contract violation fell through to the ``PROVIDER_UNAVAILABLE`` default and a
healthy provider was reported as unreachable.

Keeping the table here means a newly raised provider code has exactly one place
to be registered.
"""

from __future__ import annotations

# Provider-raised code -> domain code. Both spellings of the contract-violation
# code appear in provider modules (``message_contract`` raises
# PROVIDER_INVALID_RESPONSE, ``bailian_text`` raises PROVIDER_RESPONSE_INVALID),
# so both are mapped. Unifying the two spellings is tracked separately; until
# then, dropping either one silently mislabels the failure.
_PROVIDER_ERROR_CODES: dict[str, str] = {
    "PROVIDER_TIMEOUT": "PROVIDER_TIMEOUT",
    "PROVIDER_HTTP_ERROR": "PROVIDER_UNAVAILABLE",
    "PROVIDER_AUTH_FAILED": "PROVIDER_AUTH_FAILED",
    "PROVIDER_RATE_LIMITED": "PROVIDER_RATE_LIMITED",
    "PROVIDER_REQUEST_INVALID": "PROVIDER_REQUEST_INVALID",
    "PROVIDER_REQUEST_FAILED": "PROVIDER_UNAVAILABLE",
    "PROVIDER_RESPONSE_INVALID": "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_INVALID_RESPONSE": "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_SCRIPT_LANGUAGE_INVALID": "PROVIDER_SCRIPT_LANGUAGE_INVALID",
    "CHARACTER_PROMPT_INVALID": "CHARACTER_PROMPT_INVALID",
}

DEFAULT_PROVIDER_ERROR = "PROVIDER_UNAVAILABLE"

_H3_CODES = {
    'VIDEO_TASK_CANCELLED', 'VIDEO_GENERATION_FAILED',
    'H3_REFERENCE_UNREADABLE', 'H3_REFERENCE_UNREACHABLE', 'H3_REFERENCE_TOO_LARGE',
    'VIDEO_REQUEST_INVALID', 'VIDEO_QUOTA_EXHAUSTED', 'VIDEO_RATE_LIMITED',
    'VIDEO_CONTENT_REJECTED',
    'VIDEO_FIRST_FRAME_UNREACHABLE', 'VIDEO_FIRST_FRAME_UNREADABLE',
    'IMAGE_MODEL_UNSUPPORTED', 'IMAGE_REQUEST_INVALID', 'IMAGE_RATE_LIMITED',
    'IMAGE_QUOTA_EXHAUSTED', 'IMAGE_CONTENT_REJECTED', 'IMAGE_DOWNLOAD_FAILED',
    'IMAGE_EDIT_UNSUPPORTED', 'IMAGE_EDIT_SOURCE_UNREADABLE', 'IMAGE_EDIT_SOURCE_INVALID',
    'VIDEO_FIRST_FRAME_REQUIRED', 'VIDEO_MODE_UNSUPPORTED', 'VIDEO_DURATION_INVALID',
    'VIDEO_RESOLUTION_INVALID', 'VIDEO_PROMPT_REQUIRED', 'VIDEO_PROMPT_TOO_LONG',
    'H3_PROMPT_WRITER_REQUIRED', 'H3_SKILL_UNAVAILABLE', 'H3_PROMPT_INVALID',
    'H3_DURATION_INVALID', 'H3_REFERENCE_MODE_CONFLICT', 'H3_REFERENCE_LIMIT',
    'REFERENCE_IMAGE_INVALID', 'REFERENCE_IMAGE_PROVIDER_REQUIRED', 'MINIMAX_MODE_INVALID',
}


def map_provider_error(code: str) -> str:
    """Return the domain code for a provider-raised ``RuntimeError`` code.

    Unrecognised codes fall back to ``PROVIDER_UNAVAILABLE``, which is the
    honest answer for a provider that failed in a way we have not classified.
    """
    return code if code in _H3_CODES else _PROVIDER_ERROR_CODES.get(code, DEFAULT_PROVIDER_ERROR)
