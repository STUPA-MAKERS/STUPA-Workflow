"""Hierarchische Budgets / Kostenstellen + Haushaltsjahre (CR #76/#78, R7.1*).

Ergänzt das flache ``budget_pot``-Modell (T-17) um den **Kostenstellen-Baum**:

* :class:`Budget`            — Knoten im Baum (``parent_id`` = Self-FK; ``path_key``
  = zusammengesetzter Pfad ``VS-800-04``, vom Service gepflegt).
* :class:`FiscalYear`        — Haushaltsjahr **je Top-Level-Budget** (``budget_id``
  zeigt auf ein Top-Level; Service-Check). Disjunkt pro Top-Budget (R7.1f/g).
* :class:`BudgetAllocation`  — Top-Down-Zuteilung ``Budget × FiscalYear`` (R7.1b).
  **Verfügbare Summe = allocated; KEIN Roll-up.** Verbrauch (gebundene Summe) ist
  Roll-up aus genehmigten Anträgen (nicht persistiert; ``tree_rules.rollup_committed``).

Single-currency **EUR** (CHECK), data-model §1/§5.8. Tabellen entstehen — wie alle
Modul-Tabellen — über ``Base.metadata.create_all`` (0002); ``0020`` legt sie für
bereits migrierte Schemata idempotent nach.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Budget(UUIDPkMixin, CreatedAtMixin, Base):
    """Kostenstellen-Knoten (data-model §1 »budget«). ``parent_id`` NULL = Top-Level.

    ``gremium_id`` nur am Top-Level gesetzt (Kinder erben fachlich); ``key`` ist das
    Pfad-Segment, ``path_key`` der zusammengesetzte Schlüssel (``VS-800-04``). Self-FK
    ``ON DELETE RESTRICT`` — Kinder müssen zuerst gelöscht werden.
    """

    __tablename__ = "budget"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="RESTRICT"), nullable=True
    )
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str] = mapped_column(Text)
    path_key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Anzeigefarbe der Kostenstelle (Pie-Charts + Baum, #budget-redesign); NULL = auto.
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nur am Top-Level relevant: Flow-State-Keys, die als angenommen (→ gebunden) bzw.
    # abgelehnt (→ ausgeschlossen) gelten. Alles andere zählt als »beantragt«.
    accepted_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    denied_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")

    __table_args__ = (
        UniqueConstraint("parent_id", "key", name="uq_budget_parent_key"),
        UniqueConstraint("path_key", name="uq_budget_path_key"),
        CheckConstraint("currency = 'EUR'", name="budget_currency_eur"),
        Index("ix_budget_parent_id", "parent_id"),
        Index("ix_budget_gremium_id", "gremium_id"),
    )


class FiscalYear(UUIDPkMixin, CreatedAtMixin, Base):
    """Haushaltsjahr (R7.1d) je **Top-Level**-Budget. Start ≠ zwingend 01.01.

    Disjunkt pro Top-Budget (R7.1f): keine Überlappung der Intervalle
    ``[start_date, end_date]`` (Service-Check, ``tree_rules.intervals_overlap``).
    """

    __tablename__ = "fiscal_year"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (
        UniqueConstraint("budget_id", "label", name="uq_fiscal_year_budget_label"),
        CheckConstraint("end_date > start_date", name="fiscal_year_dates"),
        Index("ix_fiscal_year_budget_id", "budget_id"),
    )


class BudgetAllocation(UUIDPkMixin, CreatedAtMixin, Base):
    """Top-Down-Zuteilung ``Budget × FiscalYear`` (R7.1b).

    ``allocated`` = verfügbare Summe der Kostenstelle in diesem HHJ. Service-Invariante:
    Σ ``allocated`` der direkten Kinder ≤ ``allocated`` des Parents (je HHJ).
    """

    __tablename__ = "budget_allocation"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )
    allocated: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "budget_id", "fiscal_year_id", name="uq_budget_allocation_budget_fy"
        ),
        Index("ix_budget_allocation_fiscal_year_id", "fiscal_year_id"),
    )


class BudgetExpense(UUIDPkMixin, CreatedAtMixin, Base):
    """Eigenständige Ausgabe gegen eine Kostenstelle + HHJ (#25), **ohne** Antrag.

    Direkte Buchung (z. B. Barauslage, Rechnung) auf einen Budget-Knoten. Zählt —
    wie genehmigte Anträge — als **gebundener Verbrauch** und fließt im Roll-up
    (``tree_rules.rollup_committed``) über das ``path_key``-Präfix zu allen Vorfahren
    rauf. ``fiscal_year_id`` muss zum Top-Level des Knotens gehören (Service-Check).
    """

    __tablename__ = "budget_expense"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    description: Mapped[str] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="budget_expense_amount_positive"),
        CheckConstraint("currency = 'EUR'", name="budget_expense_currency_eur"),
        Index("ix_budget_expense_budget_id", "budget_id"),
        Index("ix_budget_expense_fiscal_year_id", "fiscal_year_id"),
    )


__all__ = ["Budget", "BudgetAllocation", "BudgetExpense", "FiscalYear"]
