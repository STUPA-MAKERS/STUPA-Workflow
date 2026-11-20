"""A later change of the approved amount of an approved application (spec 001620).

A person with `application.amend_decision` changes the approved amount of an
application in an approved state. The change names a reason of at least 10 characters
and the decision that allows it: the date and the Gremium. It writes a new decision
that supersedes the valid one and keeps its conditions. The state stays, so the change
writes no status event: the timeline reads the decision row (spec 001621).

The new amount may be higher than the requested amount (spec 001622), because extra
costs after the approval are the main case. It must not be negative. The dialog warns
about an amount above the request; the server only takes it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.decision import (
    Amendment,
    DecisionIn,
    check_approved_amount,
    record_decision,
    valid_decision,
)
from app.modules.applications.models import Application
from app.modules.flow.models import State
from app.modules.gremien.models import Gremium
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

#: A reason holds at least this many characters after the trim.
MIN_REASON_LENGTH = 10
MAX_REASON_LENGTH = 2000

#: The date of a decision is a date in the time zone of the student government.
BERLIN = ZoneInfo("Europe/Berlin")

CODE_NOT_APPROVED = "application_not_approved"
CODE_UNCHANGED = "approved_amount_unchanged"
CODE_DATE = "decision_date_invalid"
CODE_GREMIUM = "gremium_unknown"


class AmendIn(FrozenStrictCamelModel, frozen=True):
    """`POST /applications/{id}/approved-amount`: the new approved amount.

    Attributes:
        approved_amount: The new amount, at least 0, at most two decimals.
        reason: Why the amount changes, 10 to 2000 characters after the trim.
        decision_date: The date of the decision that allows the change, not later
            than today.
        gremium_id: The Gremium of that decision.
    """

    approved_amount: Decimal = Field(alias="approvedAmount", allow_inf_nan=False)
    reason: str
    decision_date: date = Field(alias="decisionDate")
    gremium_id: UUID = Field(alias="gremiumId")

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        """Trim the reason; refuse a short or a too long one."""
        cleaned = value.strip()
        if not MIN_REASON_LENGTH <= len(cleaned) <= MAX_REASON_LENGTH:
            raise ValueError(
                f"a reason holds {MIN_REASON_LENGTH} to {MAX_REASON_LENGTH} characters"
            )
        return cleaned


class AmendOut(FrozenCamelModel, frozen=True):
    """The result of a change: the old and the new approved amount."""

    previous_amount: Decimal | None = Field(default=None, alias="previousAmount")
    approved_amount: Decimal = Field(alias="approvedAmount")
    decided_at: datetime = Field(alias="decidedAt")


def _problem(code: str, field: str, msg: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field, "msg": msg}])


def check_amendment(
    payload: AmendIn, *, requested: Decimal | None, old: Decimal | None, today: date
) -> None:
    """Check a change against the application (pure).

    Raises:
        ValidationProblem: a bad amount (`approved_amount_invalid`), the same amount
            as before (`approved_amount_unchanged`) or a decision date after today
            (`decision_date_invalid`), 422.
    """
    check_approved_amount(requested, payload.approved_amount, allow_above=True)
    if old is not None and payload.approved_amount == old:
        raise _problem(CODE_UNCHANGED, "approvedAmount", "The approved amount is the same.")
    if payload.decision_date > today:
        raise _problem(CODE_DATE, "decisionDate", "The decision date must not be in the future.")


def berlin_today(now: datetime) -> date:
    """Return the date of `now` in Europe/Berlin."""
    return now.astimezone(BERLIN).date()


async def amend_approved_amount(
    session: AsyncSession,
    application_id: UUID,
    payload: AmendIn,
    *,
    actor: str,
    now: datetime,
) -> AmendOut:
    """Change the approved amount of an approved application (no commit).

    Raises:
        NotFoundError: The application does not exist (404).
        ConflictError: The application is not in an approved state (409
            `application_not_approved`).
        ValidationProblem: see `check_amendment`, or an unknown Gremium
            (`gremium_unknown`), 422.
    """
    app = await session.get(Application, application_id)
    if app is None:
        raise NotFoundError(f"application {application_id} not found")
    state = await session.get(State, app.current_state_id) if app.current_state_id else None
    if state is None or not state.is_approved:
        raise ConflictError(
            "Only an approved application takes a new approved amount.", code=CODE_NOT_APPROVED
        )
    old = app.approved_amount if app.approved_amount is not None else app.amount
    check_amendment(payload, requested=app.amount, old=old, today=berlin_today(now))
    known = await session.scalar(select(Gremium.id).where(Gremium.id == payload.gremium_id))
    if known is None:
        raise _problem(CODE_GREMIUM, "gremiumId", "The Gremium is unknown.")
    current = await valid_decision(session, app.id)
    row = await record_decision(
        session,
        app,
        DecisionIn(
            approvedAmount=payload.approved_amount,
            conditions=list(current.conditions or []) if current is not None else [],
        ),
        actor=actor,
        decided_by=actor,
        old_approved=old,
        now=now,
        amendment=Amendment(
            reason=payload.reason,
            basis_date=payload.decision_date,
            basis_gremium_id=payload.gremium_id,
        ),
    )
    return AmendOut(
        previousAmount=old, approvedAmount=payload.approved_amount, decidedAt=row.decided_at
    )
