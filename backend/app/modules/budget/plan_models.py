"""Haushaltsplan of a fiscal year: the plan, its versions and their lines.

A fiscal year has at most one ``BudgetPlan``. A plan has the versions 0, 1, 2 and so
on: version 0 is the Stammplan, each later one a Nachtrag. A version holds one line
per cost center below the top level. The decision logic lives in `plan_rules`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class BudgetPlan(UUIDPkMixin, CreatedAtMixin, Base):
    """Haushaltsplan of one fiscal year."""

    __tablename__ = "budget_plan"

    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )

    __table_args__ = (UniqueConstraint("fiscal_year_id", name="uq_budget_plan_fiscal_year_id"),)


class BudgetPlanVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """One version of a Haushaltsplan: the Stammplan (0) or a Nachtrag.

    ``state`` is one of ``draft``, ``in_progress``, ``in_force`` and ``replaced``.
    ``steps`` holds the steps of the budget at the moment the version left the draft,
    each as ``{"name", "gremiumId", "passedAt"}``, so a later change of the steps of
    the budget does not change a decided version. It is empty in a draft. The partial
    unique indexes keep at most one version in force and at most one version before
    ``in_force`` per plan, also under concurrent requests.
    """

    __tablename__ = "budget_plan_version"

    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budget_plan.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text, server_default="draft")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    in_force_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("plan_id", "number", name="uq_budget_plan_version_plan_id_number"),
        CheckConstraint("number >= 0", name="budget_plan_version_number"),
        CheckConstraint(
            "state IN ('draft', 'in_progress', 'in_force', 'replaced')",
            name="budget_plan_version_state",
        ),
        Index(
            "uq_budget_plan_version_in_force",
            "plan_id",
            unique=True,
            postgresql_where=text("state = 'in_force'"),
        ),
        Index(
            "uq_budget_plan_version_open",
            "plan_id",
            unique=True,
            postgresql_where=text("state IN ('draft', 'in_progress')"),
        ),
    )


class BudgetPlanStep(UUIDPkMixin, CreatedAtMixin, Base):
    """One step that a plan version of a budget passes before it comes into force.

    The steps belong to the top-level cost center. ``position`` gives their order.
    ``gremium_id`` names the Gremium that agrees in the step, or NULL for a step
    outside the platform.
    """

    __tablename__ = "budget_plan_step"

    budget_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budget.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("budget_id", "position", name="uq_budget_plan_step_budget_id_position"),
        CheckConstraint("position >= 0", name="budget_plan_step_position"),
    )


class BudgetPlanVoteSnapshot(CreatedAtMixin, Base):
    """The file of a plan version as it was when a vote on it opened (spec 000876).

    ``document`` holds what the render service needs for the PDF: ``source``,
    ``config`` and the file ``name``. The protocol of the meeting prints it as its
    Anlage, so a change of the draft after a refused vote does not change the record.
    The row has no key to the version, because it must outlive a deleted draft.
    """

    __tablename__ = "budget_plan_vote_snapshot"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE"), primary_key=True
    )
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)


class BudgetPlanLine(UUIDPkMixin, CreatedAtMixin, Base):
    """Ansatz of one cost center in one plan version.

    A cost center belongs to the plan of a year when a version has a line for it.
    ``transferable``, ``coverable`` and ``blocked`` are the Vermerke of an expense
    line. ``blocked`` is the blocked part of the Ansatz. ``side`` is ``income`` or
    ``expense`` on the line of a Titel, a direct child of the top-level cost center,
    and NULL on a line below a Titel, which has the side of its Titel. ``name`` and ``path_key``
    hold the name and the path key of the cost center at the decision, so a later
    rename does not change the text of a decided plan. They are NULL in a draft.
    """

    __tablename__ = "budget_plan_line"

    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_plan_version.id", ondelete="CASCADE")
    )
    budget_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budget.id", ondelete="CASCADE"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="0")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    path_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    side: Mapped[str | None] = mapped_column(Text, nullable=True)
    transferable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    coverable: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    blocked: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal(0), server_default="0"
    )

    __table_args__ = (
        UniqueConstraint(
            "version_id", "budget_id", name="uq_budget_plan_line_version_id_budget_id"
        ),
        CheckConstraint("amount >= 0", name="budget_plan_line_amount"),
        CheckConstraint("blocked >= 0 AND blocked <= amount", name="budget_plan_line_blocked"),
        CheckConstraint("side IN ('income', 'expense')", name="budget_plan_line_side"),
        Index("ix_budget_plan_line_budget_id", "budget_id"),
    )
