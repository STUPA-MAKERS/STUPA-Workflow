"""Notifications-Tabelle: mail_template (data-model §1).

`mail_template` hält i18n-Subject/Body (Jinja2) + deklarierte Platzhalter.
Versandlogik/Render: Service + Worker (T-18).
"""

from __future__ import annotations

from sqlalchemy import Text
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
