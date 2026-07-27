"""Legacy budget tables: budget_pot, budget_field, budget_entry.

``budget_entry`` tracks the lifecycle ``requested→reserved→approved→paid``.
Exactly one pot per application: ``budget_entry.application_id`` is UNIQUE (1:1).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

# Budget lifecycle stages. The order gives the forward direction. Config can skip
# a stage. This tuple is the single source for the model CHECK constraint and for
# the rules.
STAGES: tuple[str, ...] = ("requested", "reserved", "approved", "paid")


class BudgetPot(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "budget_pot"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    period: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (Index("ix_budget_pot_gremium_id_period", "gremium_id", "period"),)


class BudgetField(UUIDPkMixin, Base):
    """Extra field of a pot (one FormFieldDef)."""

    __tablename__ = "budget_field"

    budget_pot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_pot.id", ondelete="CASCADE")
    )
    field: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")


class BudgetEntry(UUIDPkMixin, TimestampMixin, Base):
    """Budget binding of an application to a pot, with its lifecycle.

    The relation is 1:1 with the application, so ``application_id`` is UNIQUE.
    ``amount`` syncs from the promoted ``application.amount``. ``stage`` walks
    `STAGES`. The stages ``reserved``, ``approved`` and ``paid`` count against
    ``budget_pot.total``.
    """

    __tablename__ = "budget_entry"

    budget_pot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_pot.id", ondelete="CASCADE")
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), unique=True
    )
    stage: Mapped[str] = mapped_column(Text, server_default="requested")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "stage IN ('requested', 'reserved', 'approved', 'paid')",
            name="stage",
        ),
        Index("ix_budget_entry_budget_pot_id", "budget_pot_id"),
        Index("ix_budget_entry_stage", "stage"),
    )


__all__ = ["STAGES", "BudgetEntry", "BudgetField", "BudgetPot"]
