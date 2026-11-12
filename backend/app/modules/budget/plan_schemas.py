"""Frozen camelCase DTOs of the Haushaltsplan API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.modules.budget.plan_rules import PlanState, Side
from app.shared.schemas import FrozenCamelModel

#: The largest value of ``Numeric(12, 2)``: a larger one gives 422, not a 500 from
#: the database.
_MAX_AMOUNT = Decimal("9999999999.99")


class SideSet(FrozenCamelModel, frozen=True):
    """Set the side of a direct child of a top-level cost center."""

    side: Side


class SideOut(FrozenCamelModel, frozen=True):
    """The side of a cost center after the change."""

    budget_id: UUID = Field(alias="budgetId")
    side: Side


class PlanSwitchSet(FrozenCamelModel, frozen=True):
    """Set the plan switch of a top-level cost center."""

    enabled: bool


class PlanSwitchOut(FrozenCamelModel, frozen=True):
    """The plan switch of a top-level cost center after the change."""

    budget_id: UUID = Field(alias="budgetId")
    plan_enabled: bool = Field(alias="planEnabled")


class PlanCreate(FrozenCamelModel, frozen=True):
    """Create the Haushaltsplan of a fiscal year with a Stammplan in draft.

    `copyFromFiscalYearId` names a fiscal year of the same top-level cost center. The
    Stammplan then starts with the lines of the version in force of that year.
    """

    copy_from_fiscal_year_id: UUID | None = Field(default=None, alias="copyFromFiscalYearId")


class PlanLineSet(FrozenCamelModel, frozen=True):
    """Set the line of one cost center in a draft version."""

    amount: Decimal = Field(ge=0, le=_MAX_AMOUNT, allow_inf_nan=False, decimal_places=2)
    note: str | None = Field(default=None, max_length=4000)
    transferable: bool = False
    coverable: bool = False
    blocked: Decimal = Field(
        default=Decimal(0), ge=0, le=_MAX_AMOUNT, allow_inf_nan=False, decimal_places=2
    )


class PlanStateSet(FrozenCamelModel, frozen=True):
    """Move a version to the next state, or a resolved version back to draft."""

    state: PlanState


class PlanLineOut(FrozenCamelModel, frozen=True):
    """One line of a plan version."""

    budget_id: UUID = Field(alias="budgetId")
    amount: Decimal
    note: str | None = None
    #: The name and the path key at the decision. `None` in a draft.
    name: str | None = None
    path_key: str | None = Field(default=None, alias="pathKey")
    transferable: bool = False
    coverable: bool = False
    blocked: Decimal = Decimal(0)


class PlanVersionOut(FrozenCamelModel, frozen=True):
    """One version of a Haushaltsplan with its lines."""

    id: UUID
    number: int
    state: PlanState
    created_at: datetime = Field(alias="createdAt")
    resolved_at: datetime | None = Field(default=None, alias="resolvedAt")
    approved_at: datetime | None = Field(default=None, alias="approvedAt")
    in_force_at: datetime | None = Field(default=None, alias="inForceAt")
    lines: tuple[PlanLineOut, ...] = ()


class PlanOut(FrozenCamelModel, frozen=True):
    """The Haushaltsplan of a fiscal year with every version, the Stammplan first."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    versions: tuple[PlanVersionOut, ...]
