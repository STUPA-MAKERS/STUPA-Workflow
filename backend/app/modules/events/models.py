"""The table ``event``: one Veranstaltung (F/collaboration/events/003022, 003023).

An Event belongs to one team, which gives its rights (003026). Its status is a key of the
status list ``event`` (003025), and the code reads only the phase of the status. The money,
the decisions and the other elements of an Event come from its links (``link``, kind
``event``). The series (``Reihe``) is the table ``todo_event_series`` of the to-dos.
"""

from __future__ import annotations

import uuid
from datetime import date, time

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Integer, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin
from app.modules.orders.numbers import draw_number


def format_event_number(number: str) -> str:
    """Render the number of an Event with its ``V-`` (003022)."""
    return f"V-{number}"


class Event(UUIDPkMixin, TimestampMixin, Base):
    """One Veranstaltung.

    Attributes:
        number: The eight random characters of the number, unique on the platform.
        team_id: The team; its members read and write the Event (003026).
        status: The key of a status of the list ``event`` (003025).
        shop_url: The address of the shop, http or https only (003024).
        version: Raised by each write; a change names the version it read.
        created_by: The account that created the Event, else NULL.
    """

    __tablename__ = "event"

    number: Mapped[str] = mapped_column(Text, default=draw_number, unique=True)
    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    ends_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    place: Mapped[str | None] = mapped_column(Text, nullable=True)
    participants: Mapped[int | None] = mapped_column(Integer, nullable=True)
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("todo_event_series.id", ondelete="SET NULL"), nullable=True
    )
    shop_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 300", name="title"),
        CheckConstraint(
            "ends_on IS NULL OR (starts_on IS NOT NULL AND ends_on >= starts_on)",
            name="dates",
        ),
        CheckConstraint(
            "(start_time IS NULL OR starts_on IS NOT NULL) "
            "AND (end_time IS NULL OR ends_on IS NOT NULL) "
            "AND (start_time IS NULL OR end_time IS NULL "
            "OR ends_on > starts_on OR end_time >= start_time)",
            name="times",
        ),
        CheckConstraint("participants IS NULL OR participants >= 0", name="participants"),
        CheckConstraint("shop_url IS NULL OR shop_url ~* '^https?://'", name="shop_url"),
        Index("ix_event_team_id", "team_id"),
        Index("ix_event_series_id", "series_id"),
        Index("ix_event_starts_on", "starts_on"),
    )
