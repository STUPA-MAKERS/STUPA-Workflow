"""Notifications-Tabellen: mail_template + notification_preference (data-model §1).

`mail_template` hält i18n-Subject/Body (Jinja2) + deklarierte Platzhalter.
`notification_preference` speichert die per-User-Abwahl einzelner
Benachrichtigungs-Arten (#4-2): kein Eintrag = aktiviert (Opt-out-Default).
Versandlogik/Render: Service + Worker (T-18).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


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


class NotificationPreference(Base):
    """Per-User-Schalter je Benachrichtigungs-Art (#4-2).

    Nur **Abweichungen** vom Default werden gespeichert (alle Arten sind per
    Default aktiv); essenzielle Mails (Magic-Link) sind nicht abschaltbar und
    tauchen hier nie auf. ``kind`` ∈ :data:`app.modules.notifications.kinds`.
    """

    __tablename__ = "notification_preference"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
