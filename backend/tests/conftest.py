"""Shared test configuration.

Most historical tests exercise the pre-gateway development contract by sending
``X-User-Id`` directly. That fallback is now opt-in, so enable it for the suite.
Tests that assert production behaviour delete the variable themselves.
"""

import pytest


@pytest.fixture(autouse=True)
def _trust_dev_identity_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMICFLOW_DEV_TRUST_X_USER_ID", "1")
