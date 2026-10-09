"""Approval with deviations (F1): the decision on an application.

A decision holds an approved amount (NULL = as requested) and a list of conditions
(Auflagen). Two paths write it, through the one function `record_decision`:

* the close of a passed application vote that carries a proposal (`vote.proposal`),
* a manual transition into an accepted state of the top budget of the application
  (`accepted_state_keys`) with an optional `decision` in the request.

The valid decision is the newest `application_decision` row with
`superseded_at IS NULL`. `application.approved_amount` is its denormalized copy. A new
decision supersedes the old one; nobody edits a row. An audit revert of the status
change that wrote a decision restores the decision before it
(`revert_decision_for_event`).

Each write records `application_decision` in the audit log (amounts and counts only,
never the condition texts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, ApplicationDecision
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.tree_models import Budget
from app.shared.errors import ValidationProblem

# At most this many conditions, each 1 to MAX_CONDITION_LENGTH characters (trimmed).
MAX_CONDITIONS = 20
MAX_CONDITION_LENGTH = 1000
# The largest amount of a Numeric(12, 2) column.
MAX_AMOUNT = Decimal("9999999999.99")

# The problem codes of the 422 answers.
CODE_AMOUNT_INVALID = "approved_amount_invalid"
CODE_AMOUNT_EXCEEDS = "approved_amount_exceeds_requested"
CODE_NOT_ALLOWED = "decision_not_allowed"

_CENT = Decimal("0.01")


class DecisionIn(BaseModel):
    """A decision proposal: the approved amount and the conditions.

    The body of a vote (`proposal`) and of a manual transition (`decision`) use it.
    `approvedAmount` null means "as requested". The amount rules need the requested
    amount of the application, so `check_approved_amount` runs them in the service.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    approved_amount: Decimal | None = Field(
        default=None, alias="approvedAmount", allow_inf_nan=False
    )
    conditions: list[str] = Field(default_factory=list)

    @field_validator("conditions")
    @classmethod
    def _clean_conditions(cls, value: list[str]) -> list[str]:
        """Trim each condition; refuse an empty or too long one and too many."""
        if len(value) > MAX_CONDITIONS:
            raise ValueError(f"at most {MAX_CONDITIONS} conditions")
        cleaned = [text.strip() for text in value]
        if any(not text or len(text) > MAX_CONDITION_LENGTH for text in cleaned):
            raise ValueError(f"a condition holds 1 to {MAX_CONDITION_LENGTH} characters")
        return cleaned

    def to_json(self) -> dict[str, Any]:
        """Return the stored JSON shape (`vote.proposal`): the amount as a string."""
        return {
            "approvedAmount": None if self.approved_amount is None else str(self.approved_amount),
            "conditions": list(self.conditions),
        }

    @classmethod
    def from_stored(cls, raw: object) -> DecisionIn | None:
        """Read a stored proposal. A missing or broken value gives None."""
        if not isinstance(raw, dict):
            return None
        try:
            return cls.model_validate(raw)
        except ValidationError:
            return None


def _amount_problem(code: str, msg: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": "approvedAmount", "msg": msg}])


def check_approved_amount(requested: Decimal | None, approved: Decimal | None) -> None:
    """Check the approved amount against the requested amount (pure).

    None ("as requested") always passes. Otherwise the amount must be greater than 0,
    have at most two decimals and an application amount must exist.

    Raises:
        ValidationProblem: `approved_amount_invalid` for a bad amount or an application
            without an amount, `approved_amount_exceeds_requested` for an amount above
            the requested one (422).
    """
    if approved is None:
        return
    if (
        approved <= 0
        or approved > MAX_AMOUNT
        or approved != approved.quantize(_CENT)
        or requested is None
    ):
        raise _amount_problem(
            CODE_AMOUNT_INVALID,
            "The approved amount must be greater than 0 and the application needs an amount.",
        )
    if approved > requested:
        raise _amount_problem(
            CODE_AMOUNT_EXCEEDS, "The approved amount must not exceed the requested amount."
        )


def amount_deviates(requested: Decimal | None, approved: Decimal | None) -> bool:
    """Tell whether the approved amount differs from the requested one (pure)."""
    return approved is not None and approved != requested


def committed_amount(requested: Decimal | None, approved: Decimal | None) -> Decimal | None:
    """Return the amount that the budget binds: the approved, else the requested one."""
    return approved if approved is not None else requested


def not_allowed_problem(msg: str) -> ValidationProblem:
    """Build the 422 `decision_not_allowed`."""
    return ValidationProblem(msg, code=CODE_NOT_ALLOWED, errors=[{"field": "decision", "msg": msg}])


async def accepted_state_keys(session: AsyncSession, budget_id: UUID | None) -> frozenset[str]:
    """Return the `accepted_state_keys` of the top budget of a cost center.

    The top budget is the node whose `path_key` is the first segment of the path of
    `budget_id`, as the budget view classifies the applications. No cost center gives
    an empty set.
    """
    if budget_id is None:
        return frozenset()
    top = (
        select(func.split_part(Budget.path_key, "-", 1))
        .where(Budget.id == budget_id)
        .scalar_subquery()
    )
    keys = await session.scalar(select(Budget.accepted_state_keys).where(Budget.path_key == top))
    return frozenset(k for k in keys or [] if isinstance(k, str))


async def check_decision_target(
    session: AsyncSession, app: Application, target_key: str | None
) -> None:
    """Admit a manual decision only for a target in the accepted states of the budget.

    Raises:
        ValidationProblem: `decision_not_allowed` (422).
    """
    keys = await accepted_state_keys(session, app.budget_id)
    if target_key is None or target_key not in keys:
        raise not_allowed_problem(
            "A decision is allowed only on a transition into an accepted state of the "
            "budget of the application."
        )


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


async def record_decision(
    session: AsyncSession,
    app: Application,
    decision: DecisionIn,
    *,
    actor: str | None,
    decided_by: str | None,
    old_approved: Decimal | None,
    vote_id: UUID | None = None,
    status_event_id: UUID | None = None,
    now: datetime | None = None,
) -> ApplicationDecision:
    """Write a decision in the open transaction (no commit).

    The method supersedes the valid decision, inserts the new row, sets
    `application.approved_amount` and records `application_decision`. The caller checks
    the amount (`check_approved_amount`) first. `old_approved` is the approved amount
    before this decision, for the audit entry (the flow sets the new amount before the
    guard runs).
    """
    stamp = now or datetime.now(UTC)
    await session.execute(
        update(ApplicationDecision)
        .where(
            ApplicationDecision.application_id == app.id,
            ApplicationDecision.superseded_at.is_(None),
        )
        .values(superseded_at=stamp)
    )
    row = ApplicationDecision(
        application_id=app.id,
        approved_amount=decision.approved_amount,
        conditions=list(decision.conditions),
        vote_id=vote_id,
        status_event_id=status_event_id,
        decided_at=stamp,
        decided_by=decided_by,
    )
    session.add(row)
    app.approved_amount = decision.approved_amount
    await session.flush()
    await audit_record(
        session,
        actor=actor,
        action=AuditAction.APPLICATION_DECISION,
        target_type="application",
        target_id=str(app.id),
        # Amounts and counts only: a condition is free text.
        data={
            "applicationId": str(app.id),
            "decisionId": str(row.id),
            "requestedAmount": _money(app.amount),
            "approvedAmountOld": _money(old_approved),
            "approvedAmountNew": _money(decision.approved_amount),
            "conditionCount": len(decision.conditions),
            "voteId": None if vote_id is None else str(vote_id),
            "statusEventId": None if status_event_id is None else str(status_event_id),
        },
    )
    return row


async def revert_decision_for_event(
    session: AsyncSession,
    app: Application,
    status_event_id: UUID | None,
    *,
    actor: str | None,
    now: datetime | None = None,
) -> ApplicationDecision | None:
    """Undo the decision that a reverted status change wrote (no commit).

    The method acts only while that decision is still the valid one. It supersedes the
    decision, makes the decision it superseded valid again (the row whose
    `superseded_at` is the `decided_at` of the undone one), restores
    `application.approved_amount` and records `application_decision` with
    `reverted: true`.

    Returns:
        The restored decision, or None (no decision before, or nothing to undo).
    """
    if status_event_id is None:
        return None
    undone = (
        await session.execute(
            select(ApplicationDecision).where(
                ApplicationDecision.application_id == app.id,
                ApplicationDecision.status_event_id == status_event_id,
                ApplicationDecision.superseded_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if undone is None:
        return None
    stamp = now or datetime.now(UTC)
    undone.superseded_at = stamp
    previous = (
        await session.execute(
            select(ApplicationDecision)
            .where(
                ApplicationDecision.application_id == app.id,
                ApplicationDecision.id != undone.id,
                ApplicationDecision.superseded_at == undone.decided_at,
            )
            .order_by(ApplicationDecision.decided_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    old_approved = app.approved_amount
    restored_amount: Decimal | None = None
    if previous is not None:
        previous.superseded_at = None
        restored_amount = previous.approved_amount
    app.approved_amount = restored_amount
    await session.flush()
    await audit_record(
        session,
        actor=actor,
        action=AuditAction.APPLICATION_DECISION,
        target_type="application",
        target_id=str(app.id),
        data={
            "applicationId": str(app.id),
            "decisionId": str(undone.id),
            "restoredDecisionId": None if previous is None else str(previous.id),
            "requestedAmount": _money(app.amount),
            "approvedAmountOld": _money(old_approved),
            "approvedAmountNew": _money(restored_amount),
            "conditionCount": 0 if previous is None else len(previous.conditions or []),
            "statusEventId": str(status_event_id),
            "reverted": True,
        },
    )
    return previous


async def valid_decision(
    session: AsyncSession, application_id: UUID
) -> ApplicationDecision | None:
    """Return the valid decision of an application, or None."""
    return (
        await session.execute(
            select(ApplicationDecision)
            .where(
                ApplicationDecision.application_id == application_id,
                ApplicationDecision.superseded_at.is_(None),
            )
            .order_by(ApplicationDecision.decided_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def decisions_by_event(
    session: AsyncSession, application_id: UUID
) -> dict[UUID, ApplicationDecision]:
    """Map each status event of an application to the decision it wrote."""
    rows = await session.scalars(
        select(ApplicationDecision).where(
            ApplicationDecision.application_id == application_id,
            ApplicationDecision.status_event_id.is_not(None),
        )
    )
    return {row.status_event_id: row for row in rows if row.status_event_id is not None}


@dataclass(frozen=True, slots=True)
class DecisionSource:
    """Where a decision came from: the Gremium, the meeting and the agenda number."""

    gremium_name: str | None = None
    meeting_title: str | None = None
    agenda_position: int | None = None


async def decision_source(
    session: AsyncSession, app: Application, row: ApplicationDecision
) -> DecisionSource:
    """Resolve the Gremium, the meeting title and the TOP number of a decision.

    A vote decision names the Gremium of its meeting (else of `eligible_group`), the
    meeting title and the 1-based number of its agenda item. A manual decision names
    the Gremium of the application.
    """
    from app.modules.admin.models import Gremium
    from app.modules.livevote.agenda_service import agenda_order
    from app.modules.livevote.models import Meeting, MeetingAgendaItem
    from app.modules.voting.models import Vote

    gremium_id: UUID | None = app.gremium_id
    meeting_title: str | None = None
    position: int | None = None
    vote = await session.get(Vote, row.vote_id) if row.vote_id is not None else None
    if vote is not None:
        meeting = await session.get(Meeting, vote.meeting_id) if vote.meeting_id else None
        if meeting is not None:
            gremium_id = meeting.gremium_id
            meeting_title = meeting.title
        else:
            try:
                gremium_id = UUID(vote.eligible_group)
            except (TypeError, ValueError):
                gremium_id = None
        if vote.agenda_item_id is not None and vote.meeting_id is not None:
            number = func.row_number().over(order_by=list(agenda_order())).label("n")
            ranked = (
                select(MeetingAgendaItem.id.label("item_id"), number)
                .where(MeetingAgendaItem.meeting_id == vote.meeting_id)
                .subquery()
            )
            found = await session.scalar(
                select(ranked.c.n).where(ranked.c.item_id == vote.agenda_item_id)
            )
            position = int(found) if found is not None else None
    name = (
        await session.scalar(select(Gremium.name).where(Gremium.id == gremium_id))
        if gremium_id is not None
        else None
    )
    return DecisionSource(gremium_name=name, meeting_title=meeting_title, agenda_position=position)
