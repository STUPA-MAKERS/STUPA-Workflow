"""Frozen camelCase DTOs of the Haushaltsplan API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.modules.budget.plan_rules import MAX_STEPS, PlanState, PlanTarget, Side
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
    """Bring a version into force, or move a version in progress back to draft."""

    state: PlanTarget


class PlanStepIn(FrozenCamelModel, frozen=True):
    """One step of the list a budget gets."""

    name: str = Field(min_length=1, max_length=120)
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")


class PlanStepsSet(FrozenCamelModel, frozen=True):
    """Set the ordered steps of a top-level cost center. The list can be empty."""

    steps: tuple[PlanStepIn, ...] = Field(default=(), max_length=MAX_STEPS)


class PlanStepOut(FrozenCamelModel, frozen=True):
    """One step with its Gremium, its vote, and the time it was passed in a version."""

    name: str
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    passed_at: datetime | None = Field(default=None, alias="passedAt")
    #: The vote of the Gremium on this step, and its status and result. A deleted
    #: vote leaves the id without a status.
    vote_id: UUID | None = Field(default=None, alias="voteId")
    vote_status: str | None = Field(default=None, alias="voteStatus")
    vote_result: str | None = Field(default=None, alias="voteResult")


class PlanStepsOut(FrozenCamelModel, frozen=True):
    """The steps of a top-level cost center."""

    budget_id: UUID = Field(alias="budgetId")
    steps: tuple[PlanStepOut, ...] = ()


class PlanNodeCreate(FrozenCamelModel, frozen=True):
    """Create a cost center and its line in a draft version."""

    parent_id: UUID = Field(alias="parentId")
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    name: str = Field(min_length=1, max_length=200)
    side: Side | None = None
    amount: Decimal = Field(
        default=Decimal(0), ge=0, le=_MAX_AMOUNT, allow_inf_nan=False, decimal_places=2
    )


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
    in_force_at: datetime | None = Field(default=None, alias="inForceAt")
    #: The steps of the version. A draft shows the steps of its budget, none passed.
    steps: tuple[PlanStepOut, ...] = ()
    lines: tuple[PlanLineOut, ...] = ()


class PlanOut(FrozenCamelModel, frozen=True):
    """The Haushaltsplan of a fiscal year with every version, the Stammplan first."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    versions: tuple[PlanVersionOut, ...]
