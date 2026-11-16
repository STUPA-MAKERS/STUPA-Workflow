"""Mail sending: `MailMessage` and the `MailSender` protocol (SMTP or capturing).

The module splits the domain from the transport. The service builds pure
`MailMessage` values. A `MailSender` sends them. Sending stays testable through
the capturing sender, without real SMTP. In production the worker injects the
SMTP sender.

Never log a secret or personal data. The logs carry only the recipient domains
and the idempotency key. They never carry an address, a subject, a body or the
SMTP password.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage, MIMEPart
from typing import Protocol

from app.settings import Settings

logger = logging.getLogger("app.mail")


@dataclass(frozen=True, slots=True)
class MailAttachment:
    """A mail attachment as a pure value.

    The `content` field travels base64-encoded through the queue. The platform
    sends an attachment instead of a PDF link. A link would need a login and a
    permission, and an external mailing list cannot use it.
    """

    filename: str
    mime: str
    content: bytes

    def to_payload(self) -> dict[str, object]:
        """Return the queue form, with the content base64-encoded."""
        return {
            "filename": self.filename,
            "mime": self.mime,
            "content": base64.b64encode(self.content).decode("ascii"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> MailAttachment:
        """Build the attachment from its queue form."""
        return cls(
            filename=str(payload["filename"]),
            mime=str(payload["mime"]),
            content=base64.b64decode(str(payload["content"])),
        )


@dataclass(frozen=True, slots=True)
class MailInline:
    """An image that the HTML part shows by its content id (``cid:<cid>``).

    The logo of the branding travels this way: a mail client shows an inline part
    without a click, and the mail loads nothing from a server.
    """

    cid: str
    mime: str
    content: bytes

    def to_payload(self) -> dict[str, object]:
        """Return the queue form, with the content base64-encoded."""
        return {
            "cid": self.cid,
            "mime": self.mime,
            "content": base64.b64encode(self.content).decode("ascii"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> MailInline:
        """Build the inline image from its queue form."""
        return cls(
            cid=str(payload["cid"]),
            mime=str(payload["mime"]),
            content=base64.b64decode(str(payload["content"])),
        )


@dataclass(frozen=True, slots=True)
class MailMessage:
    """A ready-to-send mail (pure value, serializable for the queue).

    Attributes:
        from_addr: Optional sender; the sender takes the default from the settings.
    """

    to: tuple[str, ...]
    subject: str
    text: str
    html: str | None = None
    idempotency_key: str = ""
    from_addr: str | None = None
    from_name: str | None = None
    attachments: tuple[MailAttachment, ...] = ()
    inline: tuple[MailInline, ...] = ()

    def recipient_domains(self) -> list[str]:
        """Return the recipient domains (for logs free of personal data)."""
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
            "inline": [i.to_payload() for i in self.inline],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> MailMessage:
        """Rebuild the message from the queue payload (inverse of `to_payload`)."""
        raw_attachments = payload.get("attachments") or []
        raw_inline = payload.get("inline") or []
        return cls(
            to=tuple(payload["to"]),  # type: ignore[arg-type]
            subject=str(payload["subject"]),
            text=str(payload["text"]),
            html=payload.get("html"),  # type: ignore[arg-type]
            idempotency_key=str(payload.get("idempotency_key", "")),
            from_addr=payload.get("from_addr"),  # type: ignore[arg-type]
            from_name=payload.get("from_name"),  # type: ignore[arg-type]
            attachments=tuple(
                MailAttachment.from_payload(a)
                for a in raw_attachments  # type: ignore[union-attr]
            ),
            inline=tuple(
                MailInline.from_payload(i)
                for i in raw_inline  # type: ignore[union-attr]
            ),
        )


def compute_idempotency_key(*parts: str) -> str:
    """Build a deterministic key from the parts (event|app|template|rcpt).

    The same input gives the same key. The queue and the sender then drop the
    duplicate, so a send is idempotent.
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"mail:{digest}"


def _add_inline(html_part: MIMEPart, images: tuple[MailInline, ...]) -> None:
    """Add each inline image to the HTML part as a related part with its content id."""
    for image in images:
        html_part.add_related(
            image.content,
            maintype=image.mime.partition("/")[0],
            subtype=image.mime.partition("/")[2],
            cid=f"<{image.cid}>",
            disposition="inline",
        )


def build_email_message(msg: MailMessage, settings: Settings) -> EmailMessage:
    """Build an RFC-5322 `EmailMessage` (text, optional HTML, attachments).

    The sender name goes through `Address`, which quotes and encodes it: the name comes
    from the branding, so it can hold a comma, a quote or a non-ASCII letter. An inline
    image joins the HTML part as a related part, so only the HTML shows it.
    """
    email = EmailMessage()
    from_addr = msg.from_addr or settings.mail_from
    from_name = " ".join((msg.from_name or settings.mail_from_name).split())
    email["From"] = Address(display_name=from_name, addr_spec=from_addr) if from_name else from_addr
    email["To"] = ", ".join(msg.to)
    email["Subject"] = msg.subject
    email.set_content(msg.text)
    if msg.html:
        email.add_alternative(msg.html, subtype="html")
        _add_inline(list(email.iter_parts())[-1], msg.inline)
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

    async def send(self, msg: MailMessage) -> None:
        """Send one mail."""
        ...


@dataclass(frozen=True, slots=True)
class CapturingMailSender:
    """Test and dev sender: collect the mails instead of sending them (no SMTP)."""

    sent: list[MailMessage] = field(default_factory=list)

    async def send(self, msg: MailMessage) -> None:
        """Collect the mail and log its domains."""
        self.sent.append(msg)
        logger.info(
            "mail captured (domains=%s key=%s)",
            msg.recipient_domains(),
            msg.idempotency_key,
        )


@dataclass(frozen=True, slots=True)
class SmtpMailSender:
    """Real async SMTP sending (aiosmtplib). The password is never logged.

    The import of aiosmtplib is local, because only the worker sends, and the API
    import stays lean.
    """

    settings: Settings

    async def send(self, msg: MailMessage) -> None:
        """Send the mail over SMTP; a mail without recipients sends nothing."""
        import aiosmtplib

        s = self.settings
        if not msg.to:
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
