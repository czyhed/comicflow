import pytest
from comicflow.notifications.adapters import ConsoleEmailAdapter, SmtpEmailAdapter


async def test_console_email_adapter_returns_delivery_id_without_exposing_token() -> None:
    adapter = ConsoleEmailAdapter()
    result = await adapter.send_magic_link(
        "creator@example.com", "secret-token-value", "https://app.test/verify"
    )
    assert result["status"] == "sent"
    assert result["deliveryId"].startswith("console-")
    assert "secret-token-value" not in str(result)


async def test_smtp_adapter_reports_missing_configuration_without_secret_values() -> None:
    adapter = SmtpEmailAdapter(
        host="",
        port=587,
        username="mailer",
        password="super-secret-password",
        sender="noreply@example.com",
    )
    with pytest.raises(RuntimeError, match="SMTP_HOST_REQUIRED") as error:
        await adapter.send_magic_link("creator@example.com", "token", "https://app.test/verify")
    assert "super-secret-password" not in str(error.value)
