"""Umlaufverfahren: a decision of a Gremium outside a meeting.

A circular vote is a ``vote`` row with ``kind = 'circular'``, without a meeting and
without an application (§F/meetings/voting/000914). ``vote.config`` holds a
``VoteConfig``: Ja / Nein / Enthaltung, the rule ``members_majority``, no quorum and
no guest ballot. It shares the life cycle of a motion, the ballot tables and the
reveal rule. The differences live here:

* The cast window: ``closesAt`` lies at least ``circularMinDays`` days after the
  open (the meeting settings). The deadline cron closes the vote at that end, and a
  manual close before it answers 409 ``circular_window_open``.
* The objection: each eligible member can object while the vote is open. The first
  objection cancels the vote with the reason ``objection``
  (§F/meetings/voting/000915).
* No delegation ballot: a delegation belongs to a meeting, and a circular vote has
  none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.meetings.models import DEFAULT_CIRCULAR_MIN_DAYS, MeetingSettings
from app.modules.voting.models import Vote
from app.modules.voting.schemas import CircularCreate, VoteCreateInternal, VoteOut
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.voting.service import VotingService

CIRCULAR = "circular"
#: The reason of a cancel by an objection (``vote.cancel_reason``).
OBJECTION = "objection"

#: 409 codes of the Umlaufverfahren.
NOT_CIRCULAR = "not_circular"
CIRCULAR_WINDOW_OPEN = "circular_window_open"
#: 422 code of a cast window that is shorter than ``circularMinDays``.
CIRCULAR_WINDOW_TOO_SHORT = "circular_window_too_short"


def is_circular(vote: object) -> bool:
    """Tell whether a vote row is an Umlaufverfahren."""
    return getattr(vote, "kind", "motion") == CIRCULAR


def circular_fields(vote: Vote) -> dict[str, Any]:
    """Return the fields of ``VoteOut`` that a circular vote sets (empty otherwise)."""
    return {"kind": CIRCULAR} if is_circular(vote) else {}


def circular_config() -> VoteConfig:
    """Return the fixed rules of a circular vote."""
    return VoteConfig(
        options=["yes", "no", "abstain"],
        majorityRule="members_majority",
        secret=True,
        tieBreak="rejected",
        guestsVote=False,
    )


def check_manual_close(vote: Vote, now: datetime | None, moment: datetime) -> None:
    """Refuse the manual close of a circular vote before its end.

    ``now`` is None for a manual close; the deadline cron passes its time.

    Raises:
        ConflictError: The cast window is still open (409 ``circular_window_open``).
    """
    if not is_circular(vote) or now is not None:
        return
    if vote.closes_at is None or vote.closes_at > moment:
        raise ConflictError(
            "The cast window of the Umlaufverfahren is still open.", code=CIRCULAR_WINDOW_OPEN
        )


def _store_objection(vote: Vote) -> None:
    """Write the reason ``objection`` on the row of a circular vote."""
    vote.cancel_reason = OBJECTION


@dataclass(frozen=True, slots=True)
class CircularService:
    """The create, the window check and the objection of a circular vote."""

    voting: VotingService

    @property
    def session(self) -> AsyncSession:
        """The session of the voting service."""
        return self.voting.session

    async def min_days(self) -> int:
        """Return ``circularMinDays`` of the meeting settings."""
        stored = await self.session.scalar(
            select(MeetingSettings.circular_min_days).where(MeetingSettings.id == 1)
        )
        return DEFAULT_CIRCULAR_MIN_DAYS if stored is None else int(stored)

    async def _check_window(self, closes_at: datetime | None, now: datetime) -> None:
        """Require the end at least ``circularMinDays`` days ahead (tz-aware).

        Raises:
            ValidationProblem: The end is missing, naive or too soon (422
                ``circular_window_too_short``).
        """
        days = await self.min_days()
        if closes_at is None or closes_at.tzinfo is None or closes_at < now + timedelta(days=days):
            raise ValidationProblem(
                f"The Umlaufverfahren runs at least {days} days.",
                code=CIRCULAR_WINDOW_TOO_SHORT,
                errors=[{"field": "closesAt", "msg": f"at least {days} days ahead"}],
            )

    async def create(
        self, payload: CircularCreate, principal: Principal, *, now: datetime
    ) -> VoteOut:
        """Create the circular vote of a Gremium, as a draft or open at once.

        The right is the right that creates a poll of the Gremium (``vote.manage`` or
        the admin role). The eligible voters are the members with ``vote.cast``.

        Raises:
            ForbiddenError: The principal lacks ``vote.manage`` in the Gremium (403).
            ValidationProblem: The Gremium does not exist (``eligible_group_invalid``)
                or the window is too short (``circular_window_too_short``) (422).
        """
        from app.modules.meetings.rules import MeetingRules
        from app.modules.voting.poll import PollService

        gremium_id = payload.eligible_group
        if not await self.voting._gremium_exists(gremium_id):
            raise ValidationProblem(
                "eligibleGroup is not the id of a gremium.",
                code="eligible_group_invalid",
                errors=[{"field": "eligibleGroup", "msg": "unknown gremium"}],
            )
        if not await PollService(self.voting).can_create(gremium_id, principal):
            raise ForbiddenError("not allowed to start an Umlaufverfahren in this gremium")
        await self._check_window(payload.closes_at, now)
        internal = VoteCreateInternal(
            config=circular_config(),
            eligibleGroup=gremium_id,
            question=payload.question,
            eligibleCount=await MeetingRules(self.session).vote_eligible_count(gremium_id),
            closesAt=payload.closes_at,
            circular=True,
        )
        created = await self.voting._insert(None, internal, actor=principal.sub)
        if payload.draft:
            return created
        return await self.voting.open(created.id, now=now, actor=principal.sub)

    async def check_open(self, vote: Vote, now: datetime) -> None:
        """Check the window of a circular draft before it opens.

        Raises:
            ValidationProblem: The window is too short (``circular_window_too_short``).
        """
        if is_circular(vote):
            await self._check_window(vote.closes_at, now)

    async def object(self, vote_id: UUID, principal: Principal, *, now: datetime) -> VoteOut:
        """Cancel an open circular vote by the objection of an eligible member.

        The first objection ends the vote: it gets no result. The audit entry
        ``vote_cancel`` names the member as the actor and the reason ``objection``.
        The caller commits.

        Raises:
            ConflictError: The vote is no circular vote (``not_circular``) or it is not
                open (``vote_not_open``).
            ForbiddenError: The principal holds no ballot in the vote, or acts with an
                OAuth token (403).
        """
        vote = await self.voting._get_vote(vote_id, for_update=True)
        if not is_circular(vote):
            raise ConflictError("The vote is no Umlaufverfahren.", code=NOT_CIRCULAR)
        if not self.voting.can_cast_own(vote, principal):
            raise ForbiddenError("Only an eligible member objects to an Umlaufverfahren.")
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot object.", code="vote_not_open")
        _store_objection(vote)
        await self.voting._mark_cancelled(vote, now=now, actor=principal.sub, reason=OBJECTION)
        await self.session.flush()
        return await self.voting.get(vote.id)
