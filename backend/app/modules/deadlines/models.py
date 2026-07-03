"""Deadline table.

A :class:`Deadline` binds a due time to an application and/or type. If
``action_on_pass`` (``{"transitionId": "<uuid>"}``) is set, the arq cron fires
that transition on expiry and then NULLs the field — the row leaves the partial
scan index, so a rerun never fires twice (idempotency marker). ``reminded_at``
marks an already-sent reminder for exactly-once semantics across workers.
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
    """Deadline for an application/type with an optional expiry action."""

    __tablename__ = "deadline"

    # NULL for type-only template deadlines.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE"), nullable=True
    )
    # Free-text classification (e.g. ``flow_phase``, ``vote``, ``requeue``);
    # informational only — the effect lives in ``action_on_pass``.
    kind: Mapped[str] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # NULL = reminder/display-only deadline. ``none_as_null=True`` is required:
    # Python ``None`` must be stored as SQL NULL, not JSONB ``'null'`` — otherwise
    # ``action_on_pass IS NOT NULL`` (scan + partial index) matches reminder-only
    # rows and ``mark_fired`` never removes a row from the scan (double firing).
    action_on_pass: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    reminded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Cron scan of expiring auto-deadlines; partial — fired rows drop out.
        Index(
            "ix_deadline_due_at_action",
            "due_at",
            postgresql_where=text("action_on_pass IS NOT NULL"),
        ),
        # Reminder scan: only not-yet-reminded deadlines.
        Index(
            "ix_deadline_reminder",
            "due_at",
            postgresql_where=text("reminded_at IS NULL"),
        ),
    )


class DeadlinePolicy(UUIDPkMixin, Base):
    """Named deadline policy (registry) referenced by the flow via ``key``.

    Decouples the concrete date from the flow definition — an ``absolute`` date
    can be updated per semester without re-versioning the flow. Kinds:
    ``absolute`` (fixed ``absolute_at``), ``relative_submitted`` /
    ``relative_changed`` (application created/updated + ``offset_days``).
    """

    __tablename__ = "deadline_policy"

    # Stable reference key used by the flow; unique.
    key: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[dict] = mapped_column(JSONB)  # I18nMap (de/en …)
    kind: Mapped[str] = mapped_column(Text)
    # Set only for ``absolute``.
    absolute_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Set only for the relative kinds (day offset).
    offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('absolute','relative_submitted','relative_changed')",
            name="deadline_policy_kind",
        ),
    )
