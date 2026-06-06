"""arq-Worker-Task: Mail-Versand (T-18).

`send_mail` rekonstruiert die `MailMessage` aus dem Queue-Payload und versendet sie
über den in `ctx` hinterlegten `MailSender` (SMTP produktiv, Capturing in DEV/Test).
Fehler → `arq.Retry` mit linearem Backoff bis `mail_max_tries`; danach »dead«
(geloggt, kein Endlos-Requeue). Idempotenz trägt der `_job_id` (= idempotency_key)
beim Enqueue — ein bereits laufender/abgeschlossener Job wird nicht doppelt erzeugt.
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
    """SMTP-Sender, wenn `smtp_host` gesetzt — sonst Capturing (DEV/Test, kein Versand)."""
    if settings.smtp_enabled:
        return SmtpMailSender(settings)
    logger.warning("SMTP not configured — mails are captured/dropped (no real send)")
    return CapturingMailSender()


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = load_settings()
    ctx["settings"] = settings
    ctx["mail_sender"] = build_sender(settings)


async def send_mail(ctx: dict[str, Any], payload: dict[str, object]) -> str:
    """Eine Mail versenden. Retry bei Fehler bis `mail_max_tries`, dann »dead«."""
    settings: Settings = ctx["settings"]
    sender: MailSender = ctx["mail_sender"]
    msg = MailMessage.from_payload(payload)
    try:
        await sender.send(msg)
    except Exception as exc:  # noqa: BLE001 — transienter SMTP-Fehler → Retry
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
