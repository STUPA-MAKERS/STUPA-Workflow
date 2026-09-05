"""Meeting table that the live votes bind to.

`Meeting` is one meeting of a Gremium. `status` drives the live-vote channel
and runs from `planned` over `live` to `closed`. `active_application_id` is the
application that the beamer shows now.
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
    """A meeting of a Gremium and anchor of the live-vote channel `meeting:{id}`."""

    __tablename__ = "meeting"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    date: Mapped[_date | None] = mapped_column(Date, nullable=True)
    # Planned start time, not the time the meeting really starts.
    start_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    # Planned end time. Without it the iCal feed assumes a default duration of
    # one hour from `start_time`. With it the value must be after `start_time`.
    end_time: Mapped[_time | None] = mapped_column(Time, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="planned")
    # The transition to `closed`, which is terminal, sets this automatically. It
    # gives the end line on the title page of the protocol.
    closed_at: Mapped[_datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active_application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    # The agenda item the room handles now. The protokollant or the session lead
    # sets it, and the followers and the beamer read it over `meeting_state`. A
    # deleted item clears the column. Unlike `active_application_id` this also
    # covers free-text items.
    current_agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_agenda_item.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The one Protokollant of the meeting. This person leads the live session
    # and writes the protocol. A deleted principal sets the column to NULL.
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
    """Attendance of one member at one meeting.

    `status` is `present`, `excused` or `absent`. `source` says who set the
    value. `self` is the member and `lead` is the meeting lead. Each pair of
    meeting and principal has exactly one row. The unique constraint drives the
    upsert.
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
    """One agenda item of a meeting, in most cases an application.

    `position` orders the applications that the meeting handles. The agenda is
    the source of the agenda items in the protocol and of the live votes. Each
    pair of meeting and application has one row.
    """

    __tablename__ = "meeting_agenda_item"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    # NULL marks a free-text agenda item with no application. The `title` column
    # then holds the text of the item.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Markdown body of this agenda item. It flows into the final protocol.
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    # A non-public item becomes a placeholder in the public protocol PDF. The
    # numbering of the agenda items stays the same.
    non_public: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        UniqueConstraint("meeting_id", "application_id", name="uq_agenda_meeting_application"),
        Index("ix_agenda_meeting", "meeting_id"),
    )
