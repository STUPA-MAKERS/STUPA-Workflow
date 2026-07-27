"""arq worker task: mail dispatch.

`send_mail` rebuilds the `MailMessage` from the queue payload and sends it with the
`MailSender` in `ctx`. Production uses SMTP. Dev and test capture the mail. On an
error the task raises `arq.Retry` with a linear backoff up to `mail_max_tries`. After
that the job is dead: the worker logs it and never requeues it again. The `_job_id`
at enqueue equals the idempotency key. It stops a duplicate job for a send that
already runs or already finished.
"""

from __future__ import annotations

import logging
from typing import Any

from arq import Retry

from app.modules.notifications.mail import (
    CapturingMailSender,
    MailMessage,
    MailSender,
    SmtpMailSender,
)
from app.settings import Settings, load_settings

logger = logging.getLogger("app.mail")


def build_sender(settings: Settings) -> MailSender:
    """Return the SMTP sender when SMTP is configured, else a capturing sender.

    The capturing sender serves dev and test. It sends no real mail.
    """
    if settings.smtp_enabled:
        return SmtpMailSender(settings)
    logger.warning("SMTP not configured — mails are captured/dropped (no real send)")
    return CapturingMailSender()


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = load_settings()
    ctx["settings"] = settings
    ctx["mail_sender"] = build_sender(settings)


async def send_mail(ctx: dict[str, Any], payload: dict[str, object]) -> str:
    """Send one mail.

    On an error the task retries with a linear backoff up to `mail_max_tries`. After
    the last try the job is dead and the worker logs it.

    Returns:
        `"sent"` after delivery, or `"dead"` after the last failed try.
    """
    settings: Settings = ctx["settings"]
    sender: MailSender = ctx["mail_sender"]
    msg = MailMessage.from_payload(payload)
    try:
        await sender.send(msg)
    except Exception as exc:  # noqa: BLE001 - transient SMTP error -> retry
        job_try = int(ctx.get("job_try", 1))
        if job_try >= settings.mail_max_tries:
            logger.error(
                "mail send failed permanently after %s tries (domains=%s key=%s)",
                job_try,
                msg.recipient_domains(),
                msg.idempotency_key,
            )
            return "dead"
        defer = settings.mail_retry_backoff_seconds * job_try
        logger.warning(
            "mail send failed (try=%s, retry in %ss, key=%s): %s",
            job_try,
            defer,
            msg.idempotency_key,
            type(exc).__name__,
        )
        raise Retry(defer=defer) from exc
    return "sent"
