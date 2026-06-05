"""Budget: budget_pot, budget_field (data-model §1 »Organisation & Config«).

Nur Tabellen (T-06). Reservierung/Buchung/Stats: T-17.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CHAR, Boolean, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


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
    """Extra-Feld eines Topfs (= eine FormFieldDef, config_schemas §5.7)."""

    __tablename__ = "budget_field"

    budget_pot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_pot.id", ondelete="CASCADE")
    )
    field: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")
