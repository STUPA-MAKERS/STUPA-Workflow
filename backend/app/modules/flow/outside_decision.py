"""A decision that a Gremium made outside the platform (specs 001600-001603).

A Gremium can decide an application in a meeting without a vote on the platform. A
person with `application.record_decision` then records the decision on the application
in its vote state: the result, the date of the meeting and the Gremium, and optionally
the counts and a link to a meeting of the platform. The result fires the `pass` or the
`fail` branch of the vote state with all of its actions and mails, as a vote close
does. The status event stores the decision for the timeline, and the audit entry of
the state change holds `outsideDecision: true`.

The record cancels every open vote of the application in the same transaction (spec
001601), as a manual exit from the vote state does, because an open vote must not
decide the application a second time. The live clients get `vote_cancelled`.

A `pass` branch into an approved state must name the approved amount (spec 001610),
as a manual approval does, because the approved amount must not depend on the way the
decision came in.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import Field
from sqlalchemy import select

from app.modules.applications.decision import DecisionIn, check_amount_given
from app.modules.auth.principal import Principal
from app.modules.flow.models import State
from app.modules.flow.service import FlowService, StagedFire
from app.modules.gremien.models import Gremium
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.schemas import FrozenStrictCamelModel

#: The date of a meeting is a date in the time zone of the student government.
BERLIN = ZoneInfo("Europe/Berlin")
#: The largest count of votes that a decision takes.
MAX_COUNT = 10000

CODE_NOT_VOTE_STATE = "not_in_vote_state"
CODE_NO_BRANCH = "no_branch"
CODE_DATE = "decision_date_invalid"
CODE_GREMIUM = "gremium_unknown"
CODE_MEETING = "meeting_unknown"

OutsideResult = Literal["passed", "failed"]


class OutsideDecisionIn(FrozenStrictCamelModel, frozen=True):
    """`POST /applications/{id}/outside-decision`: a decision made in a meeting.

    Attributes:
        result: `passed` fires the `pass` branch, `failed` the `fail` branch.
        meeting_date: The date of the meeting, not later than today.
        gremium_id: The Gremium that decided.
        yes, no, abstain: The optional counts of the votes.
        meeting_id: An optional meeting of the platform, for the link of the timeline.
        decision: The approved amount and the conditions. A `pass` branch into an
            approved state needs the amount.
    """

    result: OutsideResult
    meeting_date: date = Field(alias="meetingDate")
    gremium_id: UUID = Field(alias="gremiumId")
    yes: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    no: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    abstain: int | None = Field(default=None, ge=0, le=MAX_COUNT)
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    decision: DecisionIn | None = None

    def stored(self) -> dict[str, Any]:
        """Return the shape that the status event stores (`outside_decision`)."""
        return {
            "result": self.result,
            "meetingDate": self.meeting_date.isoformat(),
            "gremiumId": str(self.gremium_id),
            "yes": self.yes,
            "no": self.no,
            "abstain": self.abstain,
            "meetingId": None if self.meeting_id is None else str(self.meeting_id),
        }


def _problem(code: str, field: str, msg: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field, "msg": msg}])


def check_meeting_date(value: date, now: datetime) -> None:
    """Refuse a meeting date after today in Europe/Berlin (pure).

    Raises:
        ValidationProblem: `decision_date_invalid` (422).
    """
    if value > now.astimezone(BERLIN).date():
        raise _problem(CODE_DATE, "meetingDate", "The meeting date must not be in the future.")


async def record_outside_decision(
    flow: FlowService,
    application_id: UUID,
    payload: OutsideDecisionIn,
    principal: Principal,
    *,
    now: datetime | None = None,
) -> StagedFire:
    """Stage a decision made outside the platform and its branch, without a commit.

    The caller commits and then runs `FlowService.after_commit` with the result, which
    sends `vote_cancelled` for the cancelled votes and dispatches the actions. The
    decision counts only for a `passed` branch into an approved state; any other result
    drops it, because the dialog cannot see where the branch leads.

    Raises:
        NotFoundError: The application does not exist or is unconfirmed (404).
        ConflictError: The application is not in a vote state (`not_in_vote_state`),
            the state has no such branch (`no_branch`), the guard fails or a
            concurrent change won (409).
        ValidationProblem: a meeting date after today, an unknown Gremium or meeting,
            or a missing or bad approved amount (422).
    """
    session = flow.session
    check_meeting_date(payload.meeting_date, now or datetime.now(UTC))
    app = await flow._load_app(application_id, allow_unconfirmed=False)
    current = await session.get(State, app.current_state_id) if app.current_state_id else None
    if current is None or current.kind != "vote":
        raise ConflictError(
            "Only an application in a vote state takes a decision.", code=CODE_NOT_VOTE_STATE
        )
    branch = "pass" if payload.result == "passed" else "fail"
    transition = await flow.branch_transition(application_id, branch)
    if transition is None:
        raise ConflictError(f"The vote state has no '{branch}' exit.", code=CODE_NO_BRANCH)
    if await session.scalar(select(Gremium.id).where(Gremium.id == payload.gremium_id)) is None:
        raise _problem(CODE_GREMIUM, "gremiumId", "The Gremium is unknown.")
    if payload.meeting_id is not None:
        await _check_meeting(flow, payload.meeting_id, principal)
    target = await session.get(State, transition.to_state_id)
    required = await flow._amount_required(transition.from_state_id, target, app.amount)
    approves = payload.result == "passed" and target is not None and target.is_approved
    decision = payload.decision if approves else None
    check_amount_given(required, decision)
    staged = await flow.stage_fire(
        application_id,
        transition.id,
        principal,
        note=f"outside:{payload.result}",
        manual=False,
        allow_unconfirmed=False,
        decision=decision,
        outside_decision=payload.stored(),
    )
    cancelled = await flow._cancel_votes(
        app.id,
        actor=principal.sub,
        left_state_id=transition.from_state_id,
        entered_state_id=transition.to_state_id,
    )
    return replace(staged, cancelled_vote_ids=(*staged.cancelled_vote_ids, *cancelled))


async def _check_meeting(flow: FlowService, meeting_id: UUID, principal: Principal) -> None:
    """Refuse a meeting that is unknown or that the principal cannot read.

    The import is local for the same cycle as in `FlowService._check_agenda_meeting`.

    Raises:
        ValidationProblem: `meeting_unknown` (422).
    """
    from app.modules.meetings.rules import MeetingRules

    try:
        await MeetingRules(flow.session).assert_can_read(meeting_id, principal)
    except (NotFoundError, ForbiddenError) as exc:
        raise _problem(CODE_MEETING, "meetingId", "The meeting is unknown.") from exc
