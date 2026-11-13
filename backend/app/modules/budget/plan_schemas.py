"""Frozen camelCase DTOs of the Haushaltsplan API."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, Field, StrictBool, StringConstraints

from app.modules.budget.plan_rules import (
    MAX_AMOUNT,
    MAX_STEPS,
    ManualState,
    PlanState,
    PlanTarget,
    Side,
)
from app.modules.budget.tree_schemas import NodeName, visible_text
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

VoteStatus = Literal["draft", "open", "closed", "cancelled"]
VoteResult = Literal["passed", "rejected", "tie", "elected", "runoff"]

_CENT = Decimal("0.01")

#: An amount of a plan line. The validator gives every amount two decimal places, so a
#: response never shows "7" or "1E+3" for an amount that the database holds as 7.00. It
#: drops the sign of a negative zero, because the database holds 0.00 for "-0".
Amount = Annotated[
    Decimal,
    Field(ge=0, le=MAX_AMOUNT, allow_inf_nan=False, decimal_places=2),
    AfterValidator(lambda value: abs(value.quantize(_CENT))),
]

#: The name of a step, without blanks around it. A name of blanks only is empty.
StepName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    AfterValidator(visible_text),
]


class PlanSwitchSet(FrozenStrictCamelModel, frozen=True):
    """Set the plan switch of a top-level cost center."""

    enabled: bool


class PlanSwitchOut(FrozenCamelModel, frozen=True):
    """The plan switch of a top-level cost center after the change."""

    budget_id: UUID = Field(alias="budgetId")
    plan_enabled: bool = Field(alias="planEnabled")


class PlanCreate(FrozenStrictCamelModel, frozen=True):
    """Create the Haushaltsplan of a fiscal year with its first version in draft.

    `copyFromFiscalYearId` names a fiscal year of the same top-level cost center. The
    version then starts with the lines of the version in force of that year.
    """

    copy_from_fiscal_year_id: UUID | None = Field(default=None, alias="copyFromFiscalYearId")


class PlanLineSet(FrozenStrictCamelModel, frozen=True):
    """Set the line of one cost center in a draft version.

    A field that the request leaves out keeps the value of the line, so two requests
    that each change one field do not overwrite each other. A new line starts with
    the defaults. `side` belongs to the line of a Titel, a direct child of the top-level
    cost center.
    """

    side: Side | None = None
    amount: Amount = Decimal("0.00")
    note: str | None = Field(default=None, max_length=4000)
    transferable: StrictBool = False
    coverable: StrictBool = False
    blocked: Amount = Decimal("0.00")


class PlanStateSet(FrozenStrictCamelModel, frozen=True):
    """Bring a version into force, or move a version in progress back to draft."""

    state: PlanTarget


class PlanStateByHand(FrozenStrictCamelModel, frozen=True):
    """Set the state of the newest version of a plan by hand.

    `step` names the step that a version in `in_progress` waits for, by its place from
    0. The other states take no step. `reason` says why the state is set by hand.
    """

    state: ManualState
    step: int | None = Field(default=None, ge=0, lt=MAX_STEPS)
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
        AfterValidator(visible_text),
    ]


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
    #: The time a person asked for the decision of the Gremium. The step then waits
    #: for a meeting of that Gremium.
    requested_at: datetime | None = Field(default=None, alias="requestedAt")
    #: A person with `budget.plan.set_state` recorded the step, without a decision.
    by_hand: bool = Field(default=False, alias="byHand")
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
    #: The side of the line in its version: the side of its Titel, `None` while the
    #: Titel has none.
    side: Side | None = None
    amount: Decimal
    note: str | None = None
    #: The name and the path key at the decision. `None` in a draft.
    name: str | None = None
    path_key: str | None = Field(default=None, alias="pathKey")
    transferable: bool = False
    coverable: bool = False
    blocked: Decimal = Decimal(0)


class PlanMeetingOut(FrozenCamelModel, frozen=True):
    """A meeting that has a plan version on its agenda."""

    id: UUID
    title: str
    date: _date | None = None
    status: str


class WaitingPlanOut(FrozenCamelModel, frozen=True):
    """A plan version that an agenda can take, for a decision or for a reading."""

    plan_version_id: UUID = Field(alias="planVersionId")
    budget_name: str = Field(alias="budgetName")
    #: The fiscal year as the page shows it, `2026` or `2026/27`.
    fiscal_year: str = Field(alias="fiscalYear")
    #: The number of the version: 0 for the Haushaltsplan, 1 for the first Nachtrag.
    number: int
    step: str
    #: The title that the agenda item of the plan takes.
    title: str
    #: A draft that an agenda takes for a reading, without a decision (spec 000876).
    reading: bool = False


class AssignablePlansOut(FrozenCamelModel, frozen=True):
    """The plan versions that the agenda of a meeting can take (spec 000876)."""

    #: The Gremium of the meeting decides the plan of a budget in a step.
    decides: bool
    plans: tuple[WaitingPlanOut, ...]


class PlanVersionOut(FrozenCamelModel, frozen=True):
    """One version of a Haushaltsplan with its lines."""

    id: UUID
    number: int
    state: PlanState
    created_at: datetime = Field(alias="createdAt")
    in_force_at: datetime | None = Field(default=None, alias="inForceAt")
    #: The steps of the version. A draft shows the steps of its budget, none passed.
    steps: tuple[PlanStepOut, ...] = ()
    #: The meetings that have the version on their agenda, the newest first.
    meetings: tuple[PlanMeetingOut, ...] = ()
    lines: tuple[PlanLineOut, ...] = ()


class PlanOut(FrozenCamelModel, frozen=True):
    """The Haushaltsplan of a fiscal year with every version, the Stammplan first."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    versions: tuple[PlanVersionOut, ...]
