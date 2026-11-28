"""ORM models of the Mollie integration: the connection, the money data and the bookings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin
from app.shared.sealed import Sealed

#: The sources of a booking (§F/integrations/mollie/003097, 003103).
BOOKING_SOURCES = ("payment", "refund", "chargeback", "settlement")

#: The kinds of a move of money back to a payer.
MOVE_KINDS = ("refund", "chargeback")


class MollieSettings(Base):
    """The connection to one Mollie organization (single row id=1).

    Attributes:
        token: The read-only access token. No read of the API returns it
            (§NF/security/network/003101).
        organization: The name of the organization at the newest test.
        fee_budget_id: The field `Gebühren-Kostenstelle` (003097).
        unassigned_budget_id: The field `Kostenstelle für Zahlungen ohne Veranstaltung`
            (003103).
        read_ok_at: The moment of the newest read that worked (003094).
        read_error: The cause of the newest read when it failed, else NULL.
    """

    __tablename__ = "mollie_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    token: Mapped[str | None] = mapped_column(Sealed("mollie_settings.token"), nullable=True)
    organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    fee_budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )
    unassigned_budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )
    read_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class MolliePayment(Base):
    """One payment as the worker read it, only its money values (003098).

    Attributes:
        id: The id of Mollie (`tr_…`).
        fee: The fee of Mollie from the balance transactions, else NULL.
        organizer: The pretix organizer of the metadata (003095).
        event_slug: The pretix event of the metadata (003095).
    """

    __tablename__ = "mollie_payment"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    organizer: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_slug: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_mollie_payment_event", "organizer", "event_slug"),
        Index("ix_mollie_payment_settlement_id", "settlement_id"),
    )


class MollieMove(Base):
    """One refund or chargeback of a payment."""

    __tablename__ = "mollie_move"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    payment_id: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('refund','chargeback')", name="kind"),
        Index("ix_mollie_move_payment_id", "payment_id"),
    )


class MollieSettlement(Base):
    """One settlement: the sum paid out to the bank and its costs (003096, 003097)."""

    __tablename__ = "mollie_settlement"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    reference: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    fees: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class MollieBooking(UUIDPkMixin, CreatedAtMixin, Base):
    """One payment, refund, chargeback or settlement that the platform booked.

    The unique key keeps one row per source, so a second run never books twice
    (§F/integrations/mollie/003097, 003103).

    Attributes:
        source: One of `BOOKING_SOURCES`.
        source_id: The id of Mollie.
        state: `booked`, or `failed` while it waits for the next run.
        expense_id: The booking, else NULL.
        error: The short cause of the newest failure.
    """

    __tablename__ = "mollie_booking"

    source: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    expense_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_expense.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("source IN ('payment','refund','chargeback','settlement')", name="source"),
        CheckConstraint("state IN ('booked','failed')", name="state"),
        UniqueConstraint("source", "source_id", name="uq_mollie_booking_source"),
        Index("ix_mollie_booking_failed", "state"),
    )
