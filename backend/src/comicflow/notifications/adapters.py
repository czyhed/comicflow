from __future__ import annotations

import asyncio
import os
import smtplib
from email.message import EmailMessage
from secrets import token_urlsafe

from comicflow.domain.models import JsonObject


class ConsoleEmailAdapter:
    """Development adapter; deliberately omits the token from returned data."""

    async def send_magic_link(
        self, recipient: str, token: str, verify_url: str
    ) -> JsonObject:
        del token
        return {
            "status": "sent",
            "deliveryId": f"console-{token_urlsafe(8)}",
            "recipient": recipient,
            "verifyUrl": verify_url,
        }


class SmtpEmailAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        sender: str,
        use_tls: bool = True,
    ) -> None:
        self._host = host.strip()
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender.strip()
        self._use_tls = use_tls

    async def send_magic_link(
        self, recipient: str, token: str, verify_url: str
    ) -> JsonObject:
        del token
        self._validate()
        await asyncio.to_thread(self._send, recipient, verify_url)
        return {"status": "sent", "recipient": recipient}

    def _validate(self) -> None:
        if not self._host:
            raise RuntimeError("SMTP_HOST_REQUIRED")
        if not self._sender:
            raise RuntimeError("SMTP_SENDER_REQUIRED")

    def _send(self, recipient: str, verify_url: str) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = recipient
        message["Subject"] = "ComicFlow 登录链接"
        message.set_content(f"请使用此链接登录 ComicFlow：{verify_url}")
        with smtplib.SMTP(self._host, self._port, timeout=10) as client:
            if self._use_tls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password)
            client.send_message(message)


def create_email_adapter() -> ConsoleEmailAdapter | SmtpEmailAdapter:
    mode = os.getenv("COMICFLOW_EMAIL_MODE", "console").lower()
    if mode in {"console", "mailpit"}:
        return ConsoleEmailAdapter()
    if mode != "smtp":
        raise RuntimeError("EMAIL_MODE_INVALID")
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError as error:
        raise RuntimeError("SMTP_PORT_INVALID") from error
    return SmtpEmailAdapter(
        host=os.getenv("SMTP_HOST", ""),
        port=port,
        username=os.getenv("SMTP_USERNAME", ""),
        password=os.getenv("SMTP_PASSWORD", ""),
        sender=os.getenv("SMTP_SENDER", ""),
        use_tls=os.getenv("SMTP_USE_TLS", "true").lower() != "false",
    )
