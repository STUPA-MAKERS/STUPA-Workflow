"""Notifications-Tabellen (data-model §1): mail_template, notification_preference,
notification_settings, task_reminder_log.

`mail_template` hält i18n-Subject/Body (Jinja2) + deklarierte Platzhalter.
`notification_preference` speichert die per-User-Abwahl einzelner
Benachrichtigungs-Arten (#4-2): kein Eintrag = aktiviert (Opt-out-Default).
`notification_settings` ist die admin-konfigurierbare Plattform-Config
(Single-Row, #task-reminder); `task_reminder_log` merkt sich den letzten
Erinnerungs-Versand je Antrag (Einmal-/Wiederholungs-Logik).
Versandlogik/Render: Service + Worker (T-18).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
)
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


class NotificationSettings(Base):
    """Plattformweite Benachrichtigungs-Config (Single-Row, admin-gepflegt).

    Aufgaben-Erinnerungen (#task-reminder): ``task_reminder_after_days`` = Tage
    ohne Statuswechsel, bis erinnert wird; ``task_reminder_repeat_days`` = danach
    alle N Tage erneut (``0`` = nur einmal je State-Aufenthalt). Pflege über
    ``/admin/notification-settings`` (P ``admin.notifications``).
    """

    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    task_reminder_enabled: Mapped[bool] = mapped_column(
        Boolean, server_default="true"
    )
    task_reminder_after_days: Mapped[int] = mapped_column(
        Integer, server_default="5"
    )
    task_reminder_repeat_days: Mapped[int] = mapped_column(
        Integer, server_default="7"
    )

    __table_args__ = (
        # Single-Row-Garantie: es gibt genau die Zeile id=1.
        CheckConstraint("id = 1", name="notification_settings_singleton"),
        CheckConstraint(
            "task_reminder_after_days >= 1", name="task_reminder_after_days_min"
        ),
        CheckConstraint(
            "task_reminder_repeat_days >= 0", name="task_reminder_repeat_days_min"
        ),
    )


class TaskReminderLog(Base):
    """Letzter Aufgaben-Erinnerungs-Versand je Antrag (#task-reminder).

    ``status_event_id`` bindet die Erinnerung an den State-Aufenthalt: wechselt
    der Antrag den State, zählt der Aufenthalt neu (Zeile wird überschrieben).
    """

    __tablename__ = "task_reminder_log"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), primary_key=True
    )
    status_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("status_event.id", ondelete="SET NULL"), nullable=True
    )
    reminded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
