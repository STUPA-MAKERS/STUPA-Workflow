"""Mail-Versand: `MailMessage` + `MailSender`-Protokoll (SMTP / Capturing).

Trennung Domäne ↔ Transport: Der Service baut reine `MailMessage`-Werte; ein
`MailSender` versendet sie. So bleibt der Versand testbar (Capturing-Sender
fängt Mails, kein echtes SMTP) und der Worker injiziert produktiv den SMTP-Sender.

**Secrets/PII nicht loggen** (security.md §1): Logs tragen nur Empfänger-Domains +
Idempotenz-Key, nie Adressen, Betreff, Body oder das SMTP-Passwort.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from app.settings import Settings

logger = logging.getLogger("app.mail")


@dataclass(frozen=True, slots=True)
class MailMessage:
    """Eine versandfertige Mail (reiner Wert, serialisierbar für die Queue)."""

    to: tuple[str, ...]
    subject: str
    text: str
    html: str | None = None
    idempotency_key: str = ""
    # Optional gesetzte Kopf-Infos; Defaults zieht der Sender aus den Settings.
    from_addr: str | None = None
    from_name: str | None = None

    def recipient_domains(self) -> list[str]:
        """Empfänger-Domains (für Logs ohne PII)."""
        return sorted({addr.rsplit("@", 1)[-1] for addr in self.to if "@" in addr})

    def to_payload(self) -> dict[str, object]:
        """JSON-serialisierbares Dict für die arq-Queue."""
        return {
            "to": list(self.to),
            "subject": self.subject,
            "text": self.text,
            "html": self.html,
            "idempotency_key": self.idempotency_key,
            "from_addr": self.from_addr,
            "from_name": self.from_name,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> MailMessage:
        """Aus dem Queue-Payload rekonstruieren (Gegenstück zu `to_payload`)."""
        return cls(
            to=tuple(payload["to"]),  # type: ignore[arg-type]
            subject=str(payload["subject"]),
            text=str(payload["text"]),
            html=payload.get("html"),  # type: ignore[arg-type]
            idempotency_key=str(payload.get("idempotency_key", "")),
            from_addr=payload.get("from_addr"),  # type: ignore[arg-type]
            from_name=payload.get("from_name"),  # type: ignore[arg-type]
        )


def compute_idempotency_key(*parts: str) -> str:
    """Deterministischer Schlüssel aus den Bestandteilen (event|app|template|rcpt).

    Gleiche Eingabe → gleicher Key → Queue/Sender dedupliziert (idempotenter Versand).
    """
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"mail:{digest}"


def build_email_message(msg: MailMessage, settings: Settings) -> EmailMessage:
    """`MailMessage` → RFC-5322 `EmailMessage` (Text + optional HTML-Alternative)."""
    email = EmailMessage()
    from_addr = msg.from_addr or settings.mail_from
    from_name = msg.from_name or settings.mail_from_name
    email["From"] = f"{from_name} <{from_addr}>" if from_name else from_addr
    email["To"] = ", ".join(msg.to)
    email["Subject"] = msg.subject
    email.set_content(msg.text)
    if msg.html:
        email.add_alternative(msg.html, subtype="html")
    return email


class MailSender(Protocol):
    """Versand-Schnittstelle (vom Service genutzt, vom Worker injiziert)."""

    async def send(self, msg: MailMessage) -> None: ...


@dataclass(slots=True)
class CapturingMailSender:
    """Test-/DEV-Sender: sammelt Mails statt zu senden (kein echtes SMTP)."""

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
    """Echter async SMTP-Versand (aiosmtplib). Passwort wird nie geloggt."""

    settings: Settings

    async def send(self, msg: MailMessage) -> None:
        import aiosmtplib  # lokal: Worker-Pfad, hält den API-Import schlank

        s = self.settings
        if not msg.to:  # nichts zu senden (Resolver lieferte keine Empfänger)
            return
        email = build_email_message(msg, s)
        logger.info(
            "smtp send (host=%s domains=%s key=%s)",
            s.smtp_host,
            msg.recipient_domains(),
            msg.idempotency_key,
        )
        await aiosmtplib.send(  # pragma: no cover — echtes Netzwerk-I/O
            email,
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password or None,
            start_tls=s.smtp_starttls,
            use_tls=s.smtp_ssl,
            timeout=s.smtp_timeout_seconds,
        )
