"""Deadline table.

A `Deadline` binds a due time to an application, an application type, or both.
If `action_on_pass` (`{"transitionId": "<uuid>"}`) is set, the arq cron fires
that transition at expiry and then sets the field to NULL. The row leaves the
partial scan index, so a rerun never fires the transition twice. This is the
idempotency marker. `reminded_at` marks a reminder that went out already. All
workers together thus send a reminder exactly one time.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPkMixin


class Deadline(UUIDPkMixin, Base):
    """Deadline for an application or a type, with an optional expiry action."""

    __tablename__ = "deadline"

    # NULL for type-only template deadlines.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE"), nullable=True
    )
    # Free-text classification, for example `flow_phase`, `vote` or `requeue`.
    # It is informational only. The effect lives in `action_on_pass`.
    kind: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # NULL marks a reminder-only or display-only deadline. `none_as_null=True`
    # is required: Python `None` must reach the database as SQL NULL, not as
    # JSONB `'null'`. Otherwise `action_on_pass IS NOT NULL` (the scan and the
    # partial index) also matches reminder-only rows, `mark_fired` never takes
    # a row out of the scan, and the deadline fires twice.
    action_on_pass: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Cron scan of expiring auto-deadlines. The index is partial, so a
        # fired row drops out of it.
        Index(
            "ix_deadline_due_at_action",
            "due_at",
            postgresql_where=text("action_on_pass IS NOT NULL"),
        ),
        # Reminder scan. A row with a sent reminder drops out of this index.
        Index(
            "ix_deadline_reminder",
            "due_at",
            postgresql_where=text("reminded_at IS NULL"),
        ),
    )


class DeadlinePolicy(UUIDPkMixin, Base):
    """Named deadline policy in the registry, referenced by the flow through `key`.

    The policy separates the concrete date from the flow definition. An admin
    can update an `absolute` date each semester without a new flow version.

    The kinds are `absolute`, `relative_submitted`, `relative_changed` and
    `recurring`. `absolute` uses the fixed date in `absolute_at`. The relative
    kinds add `offset_days` to the creation time or the update time of the
    application. `recurring` takes the earliest of `dates` that is still ahead.
    It gives a rolling submission window.

    `at_time` and `timezone` anchor the wall clock. This is optional. If
    `at_time` (`"HH:MM"`) is set, the code snaps the resolved date to that local
    time in `timezone` and converts it to UTC. The result is DST-correct. If
    `at_time` is unset, the code keeps the historical instant arithmetic. This
    stays backward compatible.
    """

    __tablename__ = "deadline_policy"

    # Stable reference key that the flow uses.
    key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[dict] = mapped_column(JSONB)  # I18nMap with de and en keys.
    kind: Mapped[str] = mapped_column(Text)
    # Set only for `absolute`.
    absolute_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set only for the relative kinds. The unit is days.
    offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optional wall-clock anchor: `"HH:MM"` local time in `timezone`, an IANA
    # zone such as `Europe/Berlin`. If both are NULL, the code uses raw instant
    # arithmetic.
    at_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only for `recurring`: an ordered list of `"YYYY-MM-DD"` calendar dates.
    dates: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('absolute','relative_submitted','relative_changed',"
            "'recurring')",
            name="deadline_policy_kind",
        ),
    )
