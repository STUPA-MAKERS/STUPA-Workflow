"""Notifications-Tabellen: notification_rule, mail_template (data-model §1).

`notification_rule` bindet ein Event (api.md §6) an Empfänger (Gruppe/Rolle/
applicant) + einen `mail_template`-Key; `enabled=false` schaltet die Regel ab
(kein Versand). `mail_template` hält i18n-Subject/Body (Jinja2) + deklarierte
Platzhalter. Versandlogik/Render: Service + Worker (T-18).
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.modules.notifications.events import EVENTS

# DB-`CHECK` aus der Event-Whitelist (Single Source: events.EVENTS).
_EVENT_CHECK = "event IN (" + ", ".join(f"'{e}'" for e in EVENTS) + ")"


class NotificationRule(UUIDPkMixin, CreatedAtMixin, Base):
    """Regel je Event: an wen (recipients) mit welchem Template (template_key)."""

    __tablename__ = "notification_rule"

    application_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE"), nullable=True
    )
    event: Mapped[str] = mapped_column(Text)
    # recipients = [{"kind":"group","ref":"stupa"}, {"kind":"applicant"}], data-model §5.4.
    recipients: Mapped[list] = mapped_column(JSONB, server_default="[]")
    template_key: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True, server_default="true")

    __table_args__ = (
        CheckConstraint(_EVENT_CHECK, name="notification_rule_event"),
        Index("ix_notification_rule_event", "event"),
        Index(
            "ix_notification_rule_application_type_id",
            "application_type_id",
        ),
    )


class MailTemplate(UUIDPkMixin, CreatedAtMixin, Base):
    """Mail-Template: i18n-Subject/Body (Jinja2) + deklarierte Platzhalter."""

    __tablename__ = "mail_template"

    key: Mapped[str] = mapped_column(Text, unique=True)
    subject_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Body als Jinja2/Markdown; optionaler HTML-Body je Sprache separat (body_html_i18n).
    body_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    body_html_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Deklarierte Platzhalter (Doku/Vorschau): {"name": "...", "applicationId": "..."}.
    placeholders: Mapped[dict] = mapped_column(JSONB, server_default="{}")
