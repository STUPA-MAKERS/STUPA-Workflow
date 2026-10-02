"""Meeting table that the live votes bind to.

`Meeting` is one meeting of a Gremium. `status` drives the live-vote channel
and runs from `planned` over `live` to `closed`. No other transition exists: a
meeting never goes back, and a meeting that does not take place is deleted.
`active_application_id` is the application that the beamer shows now.
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
    text,
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
    # The real start (Z7). The transition from `planned` to `live` sets it once. It
    # stays NULL for a meeting that started before the column existed: the audit log
    # holds no start time for it. A reader then falls back to the planned start.
    started_at: Mapped[_datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
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
    # The current Protokollant of the meeting. This person leads the live session
    # and writes the protocol. While the meeting is live, it is the principal of the
    # running `ProtocolKeeperPeriod` (Z3), and a handover changes it. A deleted
    # principal sets the column to NULL.
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
    value. `self` is the member and `lead` is the meeting lead. A member reports
    only `present` or `excused` (Z2). Only the lead records `absent`. Each pair
    of meeting and principal has exactly one row. The unique constraint drives
    the upsert. `note` is the reason of an excuse. It is personal data.
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
        # Z2: a self-reported row is `present` or `excused`. Migration 'self status'
        # adds it NOT VALID, so the older (self, absent) rows stay as they are.
        CheckConstraint(
            "source <> 'self' OR status IN ('present','excused')", name="self_status"
        ),
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


class ProtocolKeeperPeriod(UUIDPkMixin, CreatedAtMixin, Base):
    """One period in which one principal keeps the minutes of a meeting (Z3).

    A period has three states:

    * planned: `from_at` is NULL. A handover with `mode=next_item` plans it, and
      the next forward move of the current agenda item starts it.
    * running: `from_at` is set and `to_at` is NULL. The start of the meeting opens
      the first period. A handover with `mode=now` ends the running period and opens
      the next one.
    * ended: `to_at` is set. The next period or the close of the meeting ends it.

    Each meeting has at most one running and at most one planned period (partial
    unique indexes). The agenda items mark where a period starts and ends. The
    protocol shows their number in the current agenda order, or the time when the
    item no longer exists (`SET NULL`). `principal_id` has no cascade: principal
    rows are never deleted, so the history stays. `handed_over_by` is the `sub` of
    the actor, or `system:migration` for a backfilled period.
    """

    __tablename__ = "protocol_keeper_period"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id"))
    from_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_at: Mapped[_datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # An explicit name: the generated one is longer than the 63 characters of Postgres.
    from_agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "meeting_agenda_item.id",
            ondelete="SET NULL",
            name="fk_protocol_keeper_period_from_item",
        ),
        nullable=True,
    )
    # An explicit name: the generated one is longer than the 63 characters of Postgres.
    to_agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "meeting_agenda_item.id",
            ondelete="SET NULL",
            name="fk_protocol_keeper_period_to_item",
        ),
        nullable=True,
    )
    handed_over_by: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(
            "to_at IS NULL OR (from_at IS NOT NULL AND to_at >= from_at)", name="period_range"
        ),
        Index("ix_protocol_keeper_period_meeting", "meeting_id"),
        Index(
            "uq_protocol_keeper_period_running",
            "meeting_id",
            unique=True,
            postgresql_where=text("from_at IS NOT NULL AND to_at IS NULL"),
        ),
        Index(
            "uq_protocol_keeper_period_planned",
            "meeting_id",
            unique=True,
            postgresql_where=text("from_at IS NULL"),
        ),
    )
