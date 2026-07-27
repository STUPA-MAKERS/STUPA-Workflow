"""Tables of the notifications module.

`mail_template` holds the i18n subject and body (Jinja2) and the declared
placeholders. `notification_preference` stores the per-user opt-out of one
notification kind. No row means enabled, so the default is opt-out.
`notification_settings` holds the admin-configurable platform config in a
single row. `task_reminder_log` remembers the last reminder send per
application for the once-or-repeat logic. The service and the worker do the
rendering and the sending.
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
    """Mail template: i18n subject and body (Jinja2), declared placeholders."""

    __tablename__ = "mail_template"

    key: Mapped[str] = mapped_column(Text, unique=True)
    subject_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Body as Jinja2 or Markdown. The per-language HTML body is optional.
    body_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    body_html_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Declared placeholders (docs/preview): {"name": "...", "applicationId": "..."}.
    placeholders: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class NotificationPreference(Base):
    """Per-user switch for one notification kind.

    The table stores only the **deviations** from the default. Every kind is on
    by default. A user cannot switch off an essential mail such as the magic
    link, so such a kind never appears here. The `kind` value comes from
    `app.modules.notifications.kinds`.
    """

    __tablename__ = "notification_preference"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")


class NotificationSettings(Base):
    """Platform-wide notification config (single row, admin-maintained).

    `task_reminder_after_days` counts the days without a status change until
    the first reminder goes out. `task_reminder_repeat_days` repeats the
    reminder every N days after that. A value of `0` sends the reminder only
    once per state stay. The admin manages this row under
    `/admin/notification-settings` with the `admin.notifications` permission.
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
        # Single-row guarantee: only the row with id 1 can exist.
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

    `status_event_id` binds the reminder to the state stay. When the
    application changes state, the stay starts again and the code overwrites
    the row.
    """

    __tablename__ = "task_reminder_log"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), primary_key=True
    )
    status_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("status_event.id", ondelete="SET NULL"), nullable=True
    )
    reminded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
