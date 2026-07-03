"""Meeting table — a committee session that live-votes bind to.

:class:`Meeting` — one committee session; ``status`` drives the live-vote channel
(``planned`` → ``live`` → ``closed``), ``active_application_id`` is the application
currently shown on the beamer.
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin


class Meeting(UUIDPkMixin, CreatedAtMixin, Base):
    """Committee session; anchor of the live-vote channel ``meeting:{id}``."""

    __tablename__ = "meeting"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    date: Mapped[_date | None] = mapped_column(Date, nullable=True)
    # Planned start time (optional), complements the date.
    start_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    # Planned end time (optional); if unset the iCal feed assumes a 1h default
    # duration from ``start_time``. When set, must be after ``start_time``.
    end_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="planned")
    # Set automatically on the transition to ``closed`` (terminal); provides the
    # end line of the protocol title page.
    closed_at: Mapped[_datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The single protokollant assigned per meeting; leads the live session and
    # writes the protocol. SET NULL if the principal is deleted.
    protokollant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('planned','live','closed')", name="meeting_status"
        ),
        Index("ix_meeting_gremium_id", "gremium_id"),
    )


class MeetingAttendance(UUIDPkMixin, TimestampMixin, Base):
    """Attendance per (meeting, member).

    ``status`` = present/excused/absent; ``source`` is who set it (``self`` =
    member, ``lead`` = session lead). Exactly one row per (meeting, principal),
    upserted via the unique constraint.
    """

    __tablename__ = "meeting_attendance"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="lead")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("meeting_id", "principal_id", name="uq_attendance_meeting_principal"),
        CheckConstraint(
            "status IN ('present','excused','absent')", name="attendance_status"
        ),
        CheckConstraint("source IN ('self','lead')", name="attendance_source"),
        Index("ix_attendance_meeting", "meeting_id"),
    )


class MeetingAgendaItem(UUIDPkMixin, CreatedAtMixin, Base):
    """Agenda item (TOP): an application assigned to the meeting.

    Ordered list (``position``) of applications to handle in the meeting; source
    of the protocol TOPs and live votes. One row per (meeting, application).
    """

    __tablename__ = "meeting_agenda_item"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    # NULL = free-text TOP (no application); ``title`` then holds the TOP text.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    # Free-text title of a TOP without an application.
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Markdown body of this TOP (per-TOP editor); flows into the final protocol.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    # Non-public: replaced by a placeholder in the public protocol PDF; the TOP
    # numbering is preserved.
    non_public: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        UniqueConstraint("meeting_id", "application_id", name="uq_agenda_meeting_application"),
        Index("ix_agenda_meeting", "meeting_id"),
    )
