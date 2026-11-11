"""Calendar tables: the Termin (``calendar_appointment``), its invitations and answers.

A Termin has a title, a start day and an end day. It is all-day when ``start_time`` is
NULL and timed otherwise. The times are local ``Europe/Berlin`` values without a zone,
like the times of a meeting, so the Kalender and the feed convert both the same way.

``calendar_invitation`` invites exactly one Gremium or one person per row
(``ck_calendar_invitation_target``). An invited Gremium stands for the persons who read
its meetings at the time of the read, so the row holds the Gremium and not its members.

``calendar_answer`` holds one answer per person and Termin. A change of the start or
the end deletes the answers of the Termin.

``creator_id`` is NULL after the erasure of the creator. The Termin stays for the
invited persons.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin

#: The answers of an invited person, in the order of the answer control.
ANSWERS: tuple[str, ...] = ("accept", "tentative", "decline")


class Appointment(UUIDPkMixin, TimestampMixin, Base):
    """A Termin: a dated entry of the Kalender that a person creates."""

    __tablename__ = "calendar_appointment"

    title: Mapped[str] = mapped_column(Text)
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    #: NULL for an all-day Termin. ``end_time`` is then NULL too.
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    place: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )
    #: Each signed-in person reads the Termin (the switch "Für alle").
    for_all: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    #: Counts the changes of the time or the place. The ``.ics`` file of a mail carries
    #: it as SEQUENCE, so a calendar app replaces the older copy.
    sequence: Mapped[int] = mapped_column(Integer, server_default=text("0"))

    __table_args__ = (
        CheckConstraint("ends_on >= starts_on", name="days"),
        CheckConstraint(
            "(start_time IS NULL AND end_time IS NULL) OR "
            "(start_time IS NOT NULL AND end_time IS NOT NULL AND "
            "(ends_on > starts_on OR end_time > start_time))",
            name="times",
        ),
        Index("ix_calendar_appointment_starts_on", "starts_on"),
        Index("ix_calendar_appointment_ends_on", "ends_on"),
        Index("ix_calendar_appointment_creator_id", "creator_id"),
    )


class Invitation(UUIDPkMixin, Base):
    """One invited Gremium or one invited person of a Termin."""

    __tablename__ = "calendar_invitation"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_appointment.id", ondelete="CASCADE")
    )
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("(gremium_id IS NULL) <> (principal_id IS NULL)", name="target"),
        Index(
            "uq_calendar_invitation_gremium",
            "appointment_id",
            "gremium_id",
            unique=True,
            postgresql_where=text("gremium_id IS NOT NULL"),
        ),
        Index(
            "uq_calendar_invitation_principal",
            "appointment_id",
            "principal_id",
            unique=True,
            postgresql_where=text("principal_id IS NOT NULL"),
        ),
        Index("ix_calendar_invitation_gremium_id", "gremium_id"),
        Index("ix_calendar_invitation_principal_id", "principal_id"),
    )


class Answer(Base):
    """The answer of one invited person to a Termin."""

    __tablename__ = "calendar_answer"

    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_appointment.id", ondelete="CASCADE")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id", ondelete="CASCADE"))
    answer: Mapped[str] = mapped_column(Text)
    answered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        PrimaryKeyConstraint("appointment_id", "principal_id"),
        CheckConstraint("answer IN ('accept','tentative','decline')", name="answer"),
        Index("ix_calendar_answer_principal_id", "principal_id"),
    )
