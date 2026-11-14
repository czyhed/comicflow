"""Provider error codes must map to domain codes from one table.

The mapping was previously duplicated inline at each call site, and the copies
drifted: the script-generation path omitted PROVIDER_INVALID_RESPONSE, so a
contract violation was relabelled PROVIDER_UNAVAILABLE and reported as a
provider outage.
"""

import pytest
from comicflow.providers.error_mapping import DEFAULT_PROVIDER_ERROR, map_provider_error


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        ("PROVIDER_TIMEOUT", "PROVIDER_TIMEOUT"),
        ("PROVIDER_HTTP_ERROR", "PROVIDER_UNAVAILABLE"),
        ("PROVIDER_AUTH_FAILED", "PROVIDER_AUTH_FAILED"),
        ("PROVIDER_RATE_LIMITED", "PROVIDER_RATE_LIMITED"),
        ("PROVIDER_REQUEST_INVALID", "PROVIDER_REQUEST_INVALID"),
        ("PROVIDER_REQUEST_FAILED", "PROVIDER_UNAVAILABLE"),
    ],
)
def test_transport_failures_map_to_their_own_codes(raised: str, expected: str) -> None:
    assert map_provider_error(raised) == expected


@pytest.mark.parametrize(
    "raised",
    ["PROVIDER_RESPONSE_INVALID", "PROVIDER_INVALID_RESPONSE"],
)
def test_both_spellings_of_the_contract_violation_map_to_the_domain_code(raised: str) -> None:
    """message_contract and bailian_text spell this code in opposite orders.

    Dropping either spelling sends a contract violation to the unavailable
    fallback, which blames the network for a response-shape problem.
    """
    assert map_provider_error(raised) == "PROVIDER_INVALID_RESPONSE"


def test_an_unclassified_code_falls_back_to_unavailable() -> None:
    assert map_provider_error("PROVIDER_SOMETHING_NEW") == DEFAULT_PROVIDER_ERROR
    assert DEFAULT_PROVIDER_ERROR == "PROVIDER_UNAVAILABLE"


def test_a_contract_violation_is_never_reported_as_an_outage() -> None:
    """Regression guard for the bug this module was extracted to fix."""
    for spelling in ("PROVIDER_RESPONSE_INVALID", "PROVIDER_INVALID_RESPONSE"):
        assert map_provider_error(spelling) != "PROVIDER_UNAVAILABLE"
