"""Notification tables: mail_template, notification_preference,
notification_settings, task_reminder_log.

``mail_template`` holds i18n subject/body (Jinja2) + declared placeholders.
``notification_preference`` stores the per-user opt-out of individual
notification kinds: no row = enabled (opt-out default).
``notification_settings`` is the admin-configurable platform config
(single row); ``task_reminder_log`` remembers the last reminder send per
application (once/repeat logic). Rendering/sending: service + worker.
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
    """Mail template: i18n subject/body (Jinja2) + declared placeholders."""

    __tablename__ = "mail_template"

    key: Mapped[str] = mapped_column(Text, unique=True)
    subject_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Body as Jinja2/Markdown; optional per-language HTML body (body_html_i18n).
    body_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    body_html_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Declared placeholders (docs/preview): {"name": "...", "applicationId": "..."}.
    placeholders: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class NotificationPreference(Base):
    """Per-user switch per notification kind.

    Only **deviations** from the default are stored (all kinds are on by
    default); essential mails (magic link) cannot be disabled and never
    appear here. ``kind`` ∈ :data:`app.modules.notifications.kinds`.
    """

    __tablename__ = "notification_preference"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")


class NotificationSettings(Base):
    """Platform-wide notification config (single row, admin-maintained).

    Task reminders: ``task_reminder_after_days`` = days without a status
    change until a reminder is sent; ``task_reminder_repeat_days`` = repeat
    every N days after that (``0`` = only once per state stay). Managed via
    ``/admin/notification-settings`` (permission ``admin.notifications``).
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
        # Single-row guarantee: exactly the row id=1 exists.
        CheckConstraint("id = 1", name="notification_settings_singleton"),
        CheckConstraint(
            "task_reminder_after_days >= 1", name="task_reminder_after_days_min"
        ),
        CheckConstraint(
            "task_reminder_repeat_days >= 0", name="task_reminder_repeat_days_min"
        ),
    )


class TaskReminderLog(Base):
    """Last task-reminder send per application.

    ``status_event_id`` binds the reminder to the state stay: when the
    application changes state, the stay counts anew (row is overwritten).
    """

    __tablename__ = "task_reminder_log"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), primary_key=True
    )
    status_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("status_event.id", ondelete="SET NULL"), nullable=True
    )
    reminded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
