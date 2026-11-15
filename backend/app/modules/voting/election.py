"""Personnel elections: ballot shape, stored result, lot and runoff.

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
* The next Wahlgang: ``POST /votes/{id}/next-round`` creates the draft of the second
  or the third Wahlgang of a ``members_majority`` election without a majority, on the
  same agenda item (§F/meetings/voting/000971). A stored result can still hold a
  runoff of the time before the lot decided every tie (§F/meetings/voting/000027).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

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
    VoteCreateInternal,
    VoteOut,
)
from app.shared.config_schemas import ElectionConfig
from app.shared.errors import ConflictError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.voting.service import VotingService

ELECTION = "election"

#: 409 codes of the lot.
NOT_AN_ELECTION = "not_an_election"
NO_LOT_PENDING = "no_lot_pending"
LOT_ALREADY_DRAWN = "lot_already_drawn"
#: 409 codes of the next Wahlgang.
NO_NEXT_ROUND = "no_next_round"
NEXT_ROUND_EXISTS = "next_round_exists"


def is_election(vote: object) -> bool:
    """Tell whether a vote row is an election. A row without ``kind`` is a motion."""
    return getattr(vote, "kind", "motion") == ELECTION


def election_config(vote: Vote) -> ElectionConfig:
    """Validate the stored ``ElectionConfig`` of an election row."""
    return ElectionConfig.model_validate(vote.config)


def _invalid_choice(msg: str) -> ValidationProblem:
    return ValidationProblem("Invalid election ballot.", errors=[{"field": "choice", "msg": msg}])


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


def outcome_of(
    config: ElectionConfig,
    choices: Sequence[str | None],
    eligible: int,
    round_: int,
    present: int | None = None,
) -> tally_mod.ElectionOutcome:
    """Run the pure election tally."""
    return tally_mod.tally_election(choices, config, eligible, round_=round_, present=present)


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
    """Return the election fields of ``VoteOut`` for a vote row (empty for a motion)."""
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

    A cancel or a delete of a runoff calls this. Only results stored before the lot
    decided every election tie hold a runoff (§F/meetings/voting/000027). The parent
    then shows the runoff as pending again. The method locks the parent row and clears
    the link only while it still names this runoff.
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


@dataclass(frozen=True, slots=True)
class ElectionService:
    """The lot and the runoff of an election, on the session of a ``VotingService``.

    ``choose`` is the draw function of the lot; a test passes a fixed chooser.
    """

    voting: VotingService
    choose: Callable[[Sequence[str]], str] = secrets.choice

    @property
    def session(self) -> AsyncSession:
        """The session of the voting service."""
        return self.voting.session

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

        The audit entry holds candidate ids only, so the names stay in the vote, not in
        the chain.

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
        drawn = tally_mod.draw_lot(lot.among, lot.seats, self.choose)
        decided = result.model_copy(
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
        vote.election_result = dump_result(decided)
        vote.result = "elected"
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_LOT_DRAWN,
            target_type="vote",
            target_id=str(vote.id),
            data={
                **self.voting._audit_refs(vote),
                "among": lot.among,
                "seats": lot.seats,
                "drawn": drawn,
            },
        )
        await self.session.commit()
        return await self.voting.get(vote.id)

    async def next_round(self, vote_id: UUID, principal: Principal, *, now: datetime) -> VoteOut:
        """Create the draft of the next Wahlgang of an election without a majority.

        Only a closed ``members_majority`` election with the result ``no_majority``
        takes the call, and only its first and its second Wahlgang. The second Wahlgang
        has the candidates of the first. The third has the two candidates with the most
        votes of the second; a tie for a place goes to the lot, which the result of the
        second Wahlgang and the audit log (``vote_lot_drawn``) keep. The draft sits on
        the same agenda item, and the protokollant opens it. The caller checks the
        manage right.

        Raises:
            ConflictError: The vote is no closed election (``not_an_election``), it
                takes no next Wahlgang (``no_next_round``), it has one
                (``next_round_exists``) or its meeting is not live (``meeting_closed``).
        """
        meeting_id = (await self.voting._get_vote(vote_id)).meeting_id
        if meeting_id is not None:
            await self.voting._lock_live_meeting(meeting_id)
        vote, result = await self._closed_election(vote_id)
        config = election_config(vote)
        round_ = getattr(vote, "round", 1) or 1
        if vote.result != "no_majority" or not tally_mod.needs_members_majority(config, round_):
            raise ConflictError("The election takes no next Wahlgang.", code=NO_NEXT_ROUND)
        if await self._has_next_round(vote.id):
            raise ConflictError("The election has a next Wahlgang.", code=NEXT_ROUND_EXISTS)
        standing = (
            await self._third_round_candidates(vote, config, result, principal, now)
            if (round_ + 1) >= tally_mod.SIMPLE_MAJORITY_ROUND
            else config.candidate_ids
        )
        kept = [c for c in config.candidates if c.id in standing]
        draft = await self.voting._insert(
            None,
            VoteCreateInternal(
                config=config.model_copy(update={"candidates": kept}),
                eligibleGroup=UUID(str(vote.eligible_group)),
                question=vote.question,
                parentVoteId=vote.id,
                round=round_ + 1,
                eligibleCount=vote.eligible_count,
            ),
            meeting_id=vote.meeting_id,
            agenda_item_id=vote.agenda_item_id,
            actor=principal.sub,
        )
        await self.session.commit()
        return await self.voting.get(draft.id)

    async def _has_next_round(self, vote_id: UUID) -> bool:
        """Tell whether a Wahlgang that is not cancelled continues this election."""
        stmt = select(Vote.id).where(Vote.parent_vote_id == vote_id, Vote.status != "cancelled")
        return (await self.session.scalar(stmt.limit(1))) is not None

    async def _third_round_candidates(
        self,
        vote: Vote,
        config: ElectionConfig,
        result: ElectionResultOut,
        principal: Principal,
        now: datetime,
    ) -> Sequence[str]:
        """Return the candidates of the third Wahlgang, with the lot for a tied place.

        A lot that the second Wahlgang already holds stands: a cancelled third Wahlgang
        does not draw again.
        """
        field = tally_mod.third_round_field(config.candidate_ids, result.counts)
        if not field.open_places:
            return field.sure
        stored = result.next_round_lot
        if stored is not None and stored.drawn is not None:
            return [*field.sure, *stored.drawn]
        drawn = tally_mod.draw_lot(field.tied, field.open_places, self.choose)
        lot = ElectionLotOut(
            among=list(field.tied),
            seats=field.open_places,
            drawn=drawn,
            at=now,
            by=principal.sub,
            byName=principal.display_name,
        )
        vote.election_result = dump_result(result.model_copy(update={"next_round_lot": lot}))
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_LOT_DRAWN,
            target_type="vote",
            target_id=str(vote.id),
            data={
                **self.voting._audit_refs(vote),
                "among": list(field.tied),
                "seats": field.open_places,
                "drawn": drawn,
                "for": "next_round",
            },
        )
        return [*field.sure, *drawn]
