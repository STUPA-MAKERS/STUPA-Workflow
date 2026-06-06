"""Budget: budget_pot, budget_field, budget_entry (data-model §1 »Organisation & Config«).

T-06 lieferte ``budget_pot``/``budget_field`` (nur Tabellen). T-17 ergänzt
``budget_entry`` (Lebenszyklus ``requested→reserved→approved→paid``, SDS-A1) und die
Reservier-/Buch-/Statistik-Logik (Service/Rules). Genau **ein** Topf je Antrag
(SDS-A2) → ``budget_entry.application_id`` ist UNIQUE (1:1).
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

# Budget-Lebenszyklus-Stufen (SDS-A1, overview §6). Reihenfolge = Vorwärtsrichtung;
# per Config kürzbar (Stufen überspringbar). Single Source für Modell-CHECK + Rules.
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
    """Extra-Feld eines Topfs (= eine FormFieldDef, config_schemas §5.7)."""

    __tablename__ = "budget_field"

    budget_pot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_pot.id", ondelete="CASCADE")
    )
    field: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")


class BudgetEntry(UUIDPkMixin, TimestampMixin, Base):
    """Budget-Bindung eines Antrags an einen Topf (Lebenszyklus, T-17).

    1:1 zum Antrag (``application_id`` UNIQUE, SDS-A2). ``amount`` wird aus dem
    promoted ``application.amount`` synchronisiert; ``stage`` durchläuft :data:`STAGES`
    (``reserved``/``approved``/``paid`` = gebunden → zählen gegen ``budget_pot.total``).
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
