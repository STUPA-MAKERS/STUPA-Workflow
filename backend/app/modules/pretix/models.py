"""ORM models of the pretix integration: the connection, the links and the booked orders."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.shared.sealed import Sealed

#: The sources of a booking: a paid order, or one finished refund of an order.
BOOKING_SOURCES = ("order", "refund")

#: The states of a booking row: `booked` has its booking, `failed` waits for the next run.
BOOKING_STATES = ("booked", "failed")


class PretixSettings(Base):
    """The connection to one organizer of a pretix instance (single row id=1).

    Attributes:
        base_url: The address of the instance, or NULL without a connection.
        organizer: The short name of the organizer.
        token: The token of a team of the organizer. No read of the API returns it
            (§NF/security/network/003101).
        show_sales: The switch `Verkaufszahlen zeigen` (§F/integrations/pretix/003082).
        book_income: The switch `Einnahmen buchen`. The Mollie bookings follow it too
            (§F/integrations/mollie/003097, 003103).
    """

    __tablename__ = "pretix_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    organizer: Mapped[str | None] = mapped_column(Text, nullable=True)
    token: Mapped[str | None] = mapped_column(Sealed("pretix_settings.token"), nullable=True)
    show_sales: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    book_income: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class PretixEventLink(UUIDPkMixin, CreatedAtMixin, Base):
    """The link of one Event to one pretix event (§F/integrations/pretix/003083).

    Attributes:
        event_id: The Event. Each Event links at most one pretix event.
        slug: The short name of the pretix event. Each pretix event belongs to at most
            one Event.
        name: The name of the pretix event at the moment of the link.
        date_from: The first day of the pretix event.
        income_budget_id: The field `Einnahmen-Kostenstelle` (003086), else NULL. The
            first run after it is set books every paid order, also the older ones.
        sales: The sums and numbers of 003084 from the newest read that worked, else NULL.
        sales_ok_at: The moment of the newest read that worked.
        refreshed_at: The moment of the newest read by the action `Aktualisieren`.
        created_by: The account that set the link, else NULL.
    """

    __tablename__ = "pretix_event_link"

    event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event.id", ondelete="CASCADE"), unique=True
    )
    slug: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, server_default="")
    date_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    income_budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )
    sales: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    sales_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )


class PretixBooking(UUIDPkMixin, CreatedAtMixin, Base):
    """One paid order or one refund that the platform booked (§F/integrations/pretix/003086).

    The unique key keeps one row per order and refund, so a second run never books twice.
    The row has no foreign key to its link: it stays after an unlink, so a new link of
    the same pretix event books nothing again.

    Attributes:
        slug: The pretix event of the order.
        source: One of `BOOKING_SOURCES`.
        source_key: The code of the order, and for a refund the code and the id of the
            refund (`ABC12-1`).
        state: One of `BOOKING_STATES`.
        expense_id: The booking, else NULL. A deleted booking keeps the row.
        error: The short cause of the newest failure, never a text of an exception.
    """

    __tablename__ = "pretix_booking"

    slug: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    source_key: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_expense.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("source IN ('order','refund')", name="source"),
        CheckConstraint("state IN ('booked','failed')", name="state"),
        UniqueConstraint("slug", "source", "source_key", name="uq_pretix_booking_source"),
        Index("ix_pretix_booking_failed", "state"),
    )
