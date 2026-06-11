"""Worker-Task `send_mail` (T-18): Versand, Retry, dauerhafter Fehler, Sender-Auswahl."""

from __future__ import annotations

import pytest
from arq import Retry

from app.modules.notifications.mail import CapturingMailSender, MailMessage, SmtpMailSender
from app.settings import load_settings
from worker.mail import build_sender, on_startup, send_mail

_PAYLOAD = MailMessage(
    to=("a@x.de",), subject="S", text="b", idempotency_key="k"
).to_payload()


def _ctx(sender: object, *, job_try: int = 1, max_tries: int = 5) -> dict:
    settings = load_settings(mail_max_tries=max_tries, mail_retry_backoff_seconds=10)
    return {"settings": settings, "mail_sender": sender, "job_try": job_try}


async def test_send_mail_success() -> None:
    sender = CapturingMailSender()
    result = await send_mail(_ctx(sender), _PAYLOAD)
    assert result == "sent"
    assert sender.sent[0].to == ("a@x.de",)


async def test_send_mail_retries_on_error() -> None:
    class BoomSender:
        async def send(self, msg: object) -> None:
            raise OSError("smtp down")

    with pytest.raises(Retry):
        await send_mail(_ctx(BoomSender(), job_try=1, max_tries=3), _PAYLOAD)


async def test_send_mail_dead_after_max_tries() -> None:
    class BoomSender:
        async def send(self, msg: object) -> None:
            raise OSError("smtp down")

    result = await send_mail(_ctx(BoomSender(), job_try=3, max_tries=3), _PAYLOAD)
    assert result == "dead"


def test_build_sender_capturing_without_host() -> None:
    assert isinstance(build_sender(load_settings()), CapturingMailSender)


def test_build_sender_smtp_with_host() -> None:
    sender = build_sender(load_settings(smtp_host="mail.local"))
    assert isinstance(sender, SmtpMailSender)


async def test_on_startup_populates_ctx() -> None:
    ctx: dict = {}
    await on_startup(ctx)
    assert "settings" in ctx and "mail_sender" in ctx


def test_mail_message_attachment_roundtrip() -> None:
    """#protocol-mail-pdf: Anhänge überleben die Queue (base64-Payload)."""
    from app.modules.notifications.mail import MailAttachment, MailMessage

    msg = MailMessage(
        to=("a@x.de",),
        subject="s",
        text="t",
        attachments=(
            MailAttachment(filename="p.pdf", mime="application/pdf", content=b"%PDF-1.4 x"),
        ),
    )
    again = MailMessage.from_payload(msg.to_payload())
    assert again.attachments == msg.attachments


def test_build_email_message_adds_attachment() -> None:
    from app.modules.notifications.mail import (
        MailAttachment,
        MailMessage,
        build_email_message,
    )
    from app.settings import load_settings

    msg = MailMessage(
        to=("a@x.de",),
        subject="s",
        text="t",
        attachments=(
            MailAttachment(filename="p.pdf", mime="application/pdf", content=b"%PDF-1.4 x"),
        ),
    )
    email = build_email_message(msg, load_settings())
    parts = [p for p in email.iter_attachments()]
    assert len(parts) == 1
    assert parts[0].get_filename() == "p.pdf"
    assert parts[0].get_content_type() == "application/pdf"
    assert parts[0].get_content() == b"%PDF-1.4 x"
