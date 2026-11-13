"""Frozen camelCase DTOs of the Haushaltsplan API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, StrictBool, StringConstraints

from app.modules.budget.plan_rules import MAX_AMOUNT, MAX_STEPS, PlanState, PlanTarget, Side
from app.modules.budget.tree_schemas import NodeName
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

VoteStatus = Literal["draft", "open", "closed", "cancelled"]
VoteResult = Literal["passed", "rejected", "tie", "elected", "runoff"]

_CENT = Decimal("0.01")

#: An amount of a plan line. The validator gives every amount two decimal places, so a
#: response never shows "7" or "1E+3" for an amount that the database holds as 7.00.
Amount = Annotated[
    Decimal,
    Field(ge=0, le=MAX_AMOUNT, allow_inf_nan=False, decimal_places=2),
    AfterValidator(lambda value: value.quantize(_CENT)),
]

#: The name of a step, without blanks around it. A name of blanks only is empty.
StepName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class SideSet(FrozenStrictCamelModel, frozen=True):
    """Set the side of a direct child of a top-level cost center."""

    side: Side


class SideOut(FrozenCamelModel, frozen=True):
    """The side of a cost center after the change."""

    budget_id: UUID = Field(alias="budgetId")
    side: Side


class PlanSwitchSet(FrozenStrictCamelModel, frozen=True):
    """Set the plan switch of a top-level cost center."""

    enabled: bool
    #: The person saw the allocations that the Stammplan changes and agrees.
    confirm_changes: bool = Field(default=False, alias="confirmChanges")


class PlanSwitchOut(FrozenCamelModel, frozen=True):
    """The plan switch of a top-level cost center after the change."""

    budget_id: UUID = Field(alias="budgetId")
    plan_enabled: bool = Field(alias="planEnabled")


class PlanCreate(FrozenStrictCamelModel, frozen=True):
    """Create the Haushaltsplan of a fiscal year with a Stammplan in draft.

    `copyFromFiscalYearId` names a fiscal year of the same top-level cost center. The
    Stammplan then starts with the lines of the version in force of that year.
    """

    copy_from_fiscal_year_id: UUID | None = Field(default=None, alias="copyFromFiscalYearId")


class PlanSwitchChange(FrozenCamelModel, frozen=True):
    """One allocation that the Stammplan of the plan switch changes."""

    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    year: str
    budget_id: UUID = Field(alias="budgetId")
    path_key: str = Field(alias="pathKey")
    name: str
    allocated: Decimal
    planned: Decimal


class PlanSwitchPreview(FrozenCamelModel, frozen=True):
    """What the plan switch changes when it goes on."""

    budget_id: UUID = Field(alias="budgetId")
    changes: tuple[PlanSwitchChange, ...] = ()


class PlanLineSet(FrozenStrictCamelModel, frozen=True):
    """Set the line of one cost center in a draft version.

    A field that the request leaves out keeps the value of the line, so two requests
    that each change one field do not overwrite each other. A new line starts with
    the defaults.
    """

    amount: Amount = Decimal("0.00")
    note: str | None = Field(default=None, max_length=4000)
    transferable: StrictBool = False
    coverable: StrictBool = False
    blocked: Amount = Decimal("0.00")


class PlanStateSet(FrozenStrictCamelModel, frozen=True):
    """Bring a version into force, or move a version in progress back to draft."""

    state: PlanTarget


class PlanStepIn(FrozenStrictCamelModel, frozen=True):
    """One step of the list a budget gets."""

    name: StepName
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")


class PlanStepsSet(FrozenStrictCamelModel, frozen=True):
    """Set the ordered steps of a top-level cost center. The list can be empty."""

    steps: tuple[PlanStepIn, ...] = Field(max_length=MAX_STEPS)


class PlanStepPass(FrozenStrictCamelModel, frozen=True):
    """Name the step that a request records as passed, by its place from 0."""

    step: int | None = Field(default=None, ge=0, lt=MAX_STEPS)


class PlanStepOut(FrozenCamelModel, frozen=True):
    """One step with its Gremium, its vote, and the time it was passed in a version."""

    name: str
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    passed_at: datetime | None = Field(default=None, alias="passedAt")
    #: The vote of the Gremium on this step, and its status and result. A deleted
    #: vote leaves the id without a status.
    vote_id: UUID | None = Field(default=None, alias="voteId")
    vote_status: VoteStatus | None = Field(default=None, alias="voteStatus")
    vote_result: VoteResult | None = Field(default=None, alias="voteResult")


class PlanStepsOut(FrozenCamelModel, frozen=True):
    """The steps of a top-level cost center."""

    budget_id: UUID = Field(alias="budgetId")
    steps: tuple[PlanStepOut, ...] = ()


class PlanNodeCreate(FrozenStrictCamelModel, frozen=True):
    """Create a cost center and its line in a draft version."""

    parent_id: UUID = Field(alias="parentId")
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9]+$")
    name: NodeName
    side: Side | None = None
    amount: Amount = Decimal("0.00")


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
