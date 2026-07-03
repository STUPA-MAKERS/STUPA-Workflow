"""Mail sending: ``MailMessage`` + ``MailSender`` protocol (SMTP/capturing).

Domain/transport split: the service builds pure ``MailMessage`` values; a
``MailSender`` sends them. Sending stays testable (capturing sender, no real
SMTP) and the worker injects the SMTP sender in production.

Never log secrets/PII: logs carry only recipient domains + idempotency key,
never addresses, subject, body or the SMTP password.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from app.settings import Settings

logger = logging.getLogger("app.mail")


@dataclass(frozen=True, slots=True)
class MailAttachment:
    """A mail attachment (pure value; ``content`` travels base64-encoded
    through the queue). Attachments are sent instead of PDF links because
    links would require login/permission and are useless to external lists."""

    filename: str
    mime: str
    content: bytes

    def to_payload(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "mime": self.mime,
            "content": base64.b64encode(self.content).decode("ascii"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> MailAttachment:
        return cls(
            filename=str(payload["filename"]),
            mime=str(payload["mime"]),
            content=base64.b64decode(str(payload["content"])),
        )


@dataclass(frozen=True, slots=True)
class MailMessage:
    """A ready-to-send mail (pure value, serializable for the queue)."""

    to: tuple[str, ...]
    subject: str
    text: str
    html: str | None = None
    idempotency_key: str = ""
    # Optional header info; the sender takes defaults from the settings.
    from_addr: str | None = None
    from_name: str | None = None
    attachments: tuple[MailAttachment, ...] = ()

    def recipient_domains(self) -> list[str]:
        """Return recipient domains (for PII-free logs)."""
        return sorted({addr.rsplit("@", 1)[-1] for addr in self.to if "@" in addr})

    def to_payload(self) -> dict[str, object]:
        """Return a JSON-serializable dict for the arq queue."""
        return {
            "to": list(self.to),
            "subject": self.subject,
            "text": self.text,
            "html": self.html,
            "idempotency_key": self.idempotency_key,
            "from_addr": self.from_addr,
            "from_name": self.from_name,
            "attachments": [a.to_payload() for a in self.attachments],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> MailMessage:
        """Reconstruct from the queue payload (inverse of ``to_payload``)."""
        raw_attachments = payload.get("attachments") or []
        return cls(
            to=tuple(payload["to"]),  # type: ignore[arg-type]
            subject=str(payload["subject"]),
            text=str(payload["text"]),
            html=payload.get("html"),  # type: ignore[arg-type]
            idempotency_key=str(payload.get("idempotency_key", "")),
            from_addr=payload.get("from_addr"),  # type: ignore[arg-type]
            from_name=payload.get("from_name"),  # type: ignore[arg-type]
            attachments=tuple(
                MailAttachment.from_payload(a)  # type: ignore[arg-type]
                for a in raw_attachments  # type: ignore[union-attr]
            ),
        )


def compute_idempotency_key(*parts: str) -> str:
    """Build a deterministic key from the parts (event|app|template|rcpt).

    Same input → same key → queue/sender deduplicates (idempotent sending).
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"mail:{digest}"


def build_email_message(msg: MailMessage, settings: Settings) -> EmailMessage:
    """Build an RFC-5322 ``EmailMessage`` (text + optional HTML + attachments)."""
    email = EmailMessage()
    from_addr = msg.from_addr or settings.mail_from
    from_name = msg.from_name or settings.mail_from_name
    email["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    email["To"] = ", ".join(msg.to)
    email["Subject"] = msg.subject
    email.set_content(msg.text)
    if msg.html:
        email.add_alternative(msg.html, subtype="html")
    for attachment in msg.attachments:
        maintype, _, subtype = attachment.mime.partition("/")
        email.add_attachment(
            attachment.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=attachment.filename,
        )
    return email


class MailSender(Protocol):
    """Send interface (used by the service, injected by the worker)."""

    async def send(self, msg: MailMessage) -> None: ...


@dataclass(slots=True)
class CapturingMailSender:
    """Test/dev sender: collects mails instead of sending (no real SMTP)."""

    sent: list[MailMessage] = field(default_factory=list)

    async def send(self, msg: MailMessage) -> None:
        self.sent.append(msg)
        logger.info(
            "mail captured (domains=%s key=%s)",
            msg.recipient_domains(),
            msg.idempotency_key,
        )


@dataclass(slots=True)
class SmtpMailSender:
    """Real async SMTP sending (aiosmtplib). The password is never logged."""

    settings: Settings

    async def send(self, msg: MailMessage) -> None:
        import aiosmtplib  # local: worker path, keeps the API import lean

        s = self.settings
        if not msg.to:  # nothing to send (resolver returned no recipients)
            return
        email = build_email_message(msg, s)
        logger.info(
            "smtp send (host=%s domains=%s key=%s)",
            s.smtp_host,
            msg.recipient_domains(),
            msg.idempotency_key,
        )
        await aiosmtplib.send(  # pragma: no cover — real network I/O
            email,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password or None,
            start_tls=s.smtp_starttls,
            use_tls=s.smtp_ssl,
            timeout=s.smtp_timeout_seconds,
        )
