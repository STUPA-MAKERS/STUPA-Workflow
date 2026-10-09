"""Personnel elections (F2): ballot shape, stored result, lot and runoff.

An election is a ``vote`` row with ``kind = 'election'``. ``vote.config`` holds an
``ElectionConfig`` (seats, candidates, secret, quorum, guests). It shares the life
cycle of a motion (draft -> open -> closed / cancelled), the race-safe ballot tables
and the reveal rule. The differences live here:

* The ballot: a JSON list of candidate ids (at most ``seats``, no id twice, ``[]`` =
  full abstention), or ``yes``/``no``/``abstain`` for one candidate on one seat.
* The close: ``tally.tally_election`` decides; the vote stores ``election_result``
  and fires no flow branch (an election never has an application).
* The lot: ``POST /votes/{id}/draw-lot`` draws with ``secrets.choice`` when a tie is
  pending, audits ``vote_lot_drawn`` and refuses a second draw.
* The runoff: ``POST /votes/{id}/runoff`` creates the draft runoff with the tied
  candidates and the open seats, on the same agenda item, one round later.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Vote
from app.modules.voting.schemas import (
    ElectionLotOut,
    ElectionResultOut,
    ElectionRunoffOut,
    MyBallot,
    VoteCreateInternal,
    VoteOut,
)
from app.shared.config_schemas import ElectionConfig
from app.shared.errors import ConflictError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.voting.service import VotingService

ELECTION = "election"

# 409 codes of the lot and the runoff.
NOT_AN_ELECTION = "not_an_election"
NO_LOT_PENDING = "no_lot_pending"
LOT_ALREADY_DRAWN = "lot_already_drawn"
NO_RUNOFF_PENDING = "no_runoff_pending"
RUNOFF_EXISTS = "runoff_exists"


def is_election(vote: object) -> bool:
    """Tell whether a vote row is an election. A row without ``kind`` is a motion."""
    return getattr(vote, "kind", "motion") == ELECTION


def election_config(vote: Vote) -> ElectionConfig:
    """Validate the stored ``ElectionConfig`` of an election row."""
    return ElectionConfig.model_validate(vote.config)


def _invalid_choice(msg: str) -> ValidationProblem:
    return ValidationProblem(
        "Invalid election ballot.", errors=[{"field": "choice", "msg": msg}]
    )


def stored_choice(config: ElectionConfig, choice: str | list[str]) -> str:
    """Check an election ballot and return its stored form.

    Raises:
        ValidationProblem: The ballot does not fit the election (422).
    """
    if config.yes_no:
        if not isinstance(choice, str) or choice not in ("yes", "no", "abstain"):
            raise _invalid_choice("yes, no or abstain")
        return choice
    if not isinstance(choice, list):
        raise _invalid_choice("a list of candidate ids")
    if len(set(choice)) != len(choice):
        raise _invalid_choice("a candidate is chosen twice")
    if len(choice) > config.seats:
        raise _invalid_choice("more votes than seats")
    if not set(choice) <= set(config.candidate_ids):
        raise _invalid_choice("unknown candidate")
    return tally_mod.encode_election_choice(choice)


def own_ballot(kind: str, choice: str | None) -> MyBallot:
    """Build the own ballot of an open vote row (a cast ``ballot`` row).

    An election ballot with several candidates gives the chosen ids in ``choices``.
    """
    if kind == ELECTION:
        picks = tally_mod.decode_election_choice(choice)
        if picks is not None:
            return MyBallot(cast=True, choices=picks)
    return MyBallot(cast=True, choice=choice)


def outcome_of(
    config: ElectionConfig, choices: Sequence[str | None], eligible: int, round_: int
) -> tally_mod.ElectionOutcome:
    """Run the pure election tally."""
    return tally_mod.tally_election(choices, config, eligible, round_=round_)


def result_of(outcome: tally_mod.ElectionOutcome) -> ElectionResultOut:
    """Build the stored result from the tally of a closed election."""
    runoff = (
        ElectionRunoffOut(candidateIds=list(outcome.tied), seats=outcome.open_seats)
        if outcome.result == "runoff"
        else None
    )
    lot = (
        ElectionLotOut(among=list(outcome.tied), seats=outcome.open_seats)
        if outcome.result == "tie"
        else None
    )
    return ElectionResultOut(
        counts=dict(outcome.counts),
        abstentions=outcome.abstentions,
        ballots=outcome.ballots,
        yes=outcome.yes,
        no=outcome.no,
        elected=list(outcome.elected),
        runoff=runoff,
        lot=lot,
    )


def dump_result(result: ElectionResultOut) -> dict[str, Any]:
    """Return the JSONB form of an election result."""
    return result.model_dump(mode="json", by_alias=True)


def election_fields(vote: Vote) -> dict[str, Any]:
    """Return the F2 fields of ``VoteOut`` for a vote row (empty for a motion)."""
    if not is_election(vote):
        return {}
    stored = getattr(vote, "election_result", None)
    return {
        "kind": ELECTION,
        "election": election_config(vote),
        "electionResult": ElectionResultOut.model_validate(stored) if stored else None,
        "parentVoteId": getattr(vote, "parent_vote_id", None),
        "round": getattr(vote, "round", 1) or 1,
    }


async def release_runoff_link(session: AsyncSession, vote: Vote) -> None:
    """Clear the link of the parent election to a runoff that goes away (no commit).

    A cancel or a delete of a runoff calls this. The parent then shows the runoff as
    pending again, and ``POST /votes/{parent}/runoff`` creates a new one. The method
    locks the parent row, as ``create_runoff`` does, and clears the link only while it
    still names this runoff.
    """
    parent_id = getattr(vote, "parent_vote_id", None)
    if not is_election(vote) or parent_id is None:
        return
    parent = (
        await session.execute(select(Vote).where(Vote.id == parent_id).with_for_update())
    ).scalar_one_or_none()
    stored = None if parent is None else getattr(parent, "election_result", None)
    if parent is None or not stored:
        return
    result = ElectionResultOut.model_validate(stored)
    runoff = result.runoff
    if runoff is None or runoff.vote_id != vote.id:
        return
    parent.election_result = dump_result(
        result.model_copy(update={"runoff": runoff.model_copy(update={"vote_id": None})})
    )


class ElectionService:
    """The lot and the runoff of an election, on the session of a ``VotingService``."""

    def __init__(
        self, voting: VotingService, choose: Callable[[Sequence[str]], str] = secrets.choice
    ) -> None:
        self.voting = voting
        self.session = voting.session
        self._choose = choose

    async def _closed_election(self, vote_id: UUID) -> tuple[Vote, ElectionResultOut]:
        """Lock a closed election and return it with its stored result.

        Raises:
            NotFoundError: No vote has this id.
            ConflictError: The vote is no closed election (``not_an_election``).
        """
        vote = await self.voting._get_vote(vote_id, for_update=True)
        stored = getattr(vote, "election_result", None)
        if not is_election(vote) or vote.status != "closed" or not stored:
            raise ConflictError("The vote is no closed election.", code=NOT_AN_ELECTION)
        return vote, ElectionResultOut.model_validate(stored)

    async def draw_lot(self, vote_id: UUID, principal: Principal, *, now: datetime) -> VoteOut:
        """Draw the lot of a pending tie and elect the drawn candidates.

        The server draws with ``secrets.choice``, one seat at a time. The result keeps
        the candidates, the moment and the meeting lead who triggered the draw, and
        the audit log gets ``vote_lot_drawn``. The caller checks the manage right.

        Raises:
            ConflictError: The vote is no closed election (``not_an_election``), no
                lot is pending (``no_lot_pending``) or the lot was drawn
                (``lot_already_drawn``).
        """
        vote, result = await self._closed_election(vote_id)
        lot = result.lot
        if lot is None:
            raise ConflictError("No lot is pending for this election.", code=NO_LOT_PENDING)
        if lot.drawn is not None:
            raise ConflictError("The lot was already drawn.", code=LOT_ALREADY_DRAWN)
        drawn = tally_mod.draw_lot(lot.among, lot.seats, self._choose)
        result = result.model_copy(
            update={
                "elected": [*result.elected, *drawn],
                "lot": lot.model_copy(
                    update={
                        "drawn": drawn,
                        "at": now,
                        "by": principal.sub,
                        "by_name": principal.display_name,
                    }
                ),
            }
        )
        vote.election_result = dump_result(result)
        vote.result = "elected"
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_LOT_DRAWN,
            target_type="vote",
            target_id=str(vote.id),
            # Candidate ids only: the names stay in the vote, not in the chain.
            data={
                **self.voting._audit_refs(vote),
                "among": lot.among,
                "seats": lot.seats,
                "drawn": drawn,
            },
        )
        await self.session.commit()
        return await self.voting.get(vote.id)

    async def _runoff_alive(self, runoff_id: UUID) -> bool:
        """Tell whether a linked runoff still exists and is not cancelled.

        A cancelled or deleted runoff no longer blocks a new one.
        """
        status = await self.session.scalar(select(Vote.status).where(Vote.id == runoff_id))
        return status is not None and status != "cancelled"

    async def create_runoff(self, vote_id: UUID) -> VoteOut:
        """Create the draft runoff of an election with a tie at the seat boundary.

        The runoff takes the tied candidates and the open seats, the rules of its
        parent (secret, quorum, guests), the same meeting and agenda item, and round
        ``parent + 1``. The eligible count comes from the roster again. The meeting
        lead opens it with ``POST /votes/{id}/open``. The caller checks the manage
        right.

        Raises:
            ConflictError: The vote is no closed election (``not_an_election``), no
                runoff is pending (``no_runoff_pending``), a runoff exists that is
                not cancelled (``runoff_exists``) or the meeting is not live.
        """
        # Lock order: the meeting row first, the vote row after it (as the meeting
        # close and delete do).
        meeting_id = await self.session.scalar(select(Vote.meeting_id).where(Vote.id == vote_id))
        if meeting_id is not None:
            await self.voting._lock_live_meeting(meeting_id)
        vote, result = await self._closed_election(vote_id)
        runoff = result.runoff
        if runoff is None:
            raise ConflictError(
                "No runoff is pending for this election.", code=NO_RUNOFF_PENDING
            )
        if runoff.vote_id is not None and await self._runoff_alive(runoff.vote_id):
            raise ConflictError("The runoff of this election exists.", code=RUNOFF_EXISTS)
        parent = election_config(vote)
        tied = set(runoff.candidate_ids)
        config = parent.model_copy(
            update={
                "seats": runoff.seats,
                "candidates": [c for c in parent.candidates if c.id in tied],
            }
        )
        eligible = vote.eligible_count
        if not parent.guests_vote:
            from app.modules.livevote.service import MeetingService

            eligible = await MeetingService(self.session).vote_eligible_count(
                UUID(vote.eligible_group)
            )
        payload = VoteCreateInternal(
            config=ElectionConfig.model_validate(config.model_dump(by_alias=True)),
            eligibleGroup=UUID(vote.eligible_group),
            question=vote.question,
            eligibleCount=eligible,
            parentVoteId=vote.id,
            round=(getattr(vote, "round", 1) or 1) + 1,
        )
        # The link to the runoff joins the commit of the insert, so a second call
        # sees it under the row lock and gets 409.
        runoff_id = uuid4()
        vote.election_result = dump_result(
            result.model_copy(update={"runoff": runoff.model_copy(update={"vote_id": runoff_id})})
        )
        return await self.voting._insert(
            None,
            payload,
            meeting_id=vote.meeting_id,
            agenda_item_id=vote.agenda_item_id,
            vote_id=runoff_id,
        )
