"""Meeting-bound vote reads: tally reload, reveal rule, and quorum helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.modules.applications.decision import DecisionIn
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import Gremium
from app.modules.livevote.schemas import MeetingVoteOut
from app.modules.livevote.service.service_base import MeetingServiceBase
from app.modules.meetings import present as present_mod
from app.modules.meetings.models import MeetingGuest
from app.modules.meetings.present import NOBODY, Present, present_count
from app.modules.voting.election import election_config, election_fields, is_election
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.voting.poll import is_poll, poll_config, poll_fields, result_of
from app.modules.voting.schemas import MyBallot
from app.modules.voting.tally import ElectionOutcome, PollOutcome, tally_election, tally_poll
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ValidationProblem

#: The reload tally of one vote: counts, leading option and failed reason.
_Tally = tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None]
_NO_TALLY: _Tally = (None, None, None)
#: The display aggregates of one vote: counts, leading option, voted and failed reason.
_Aggregates = tuple[dict[str, int] | None, str | None, int, Literal["quorum", "majority"] | None]


@dataclass(frozen=True, slots=True)
class _VoteReads:
    """The batched reads that the reload path needs to build the votes of meetings."""

    tallies: Mapping[UUID, _Tally]
    elections: Mapping[UUID, ElectionOutcome]
    polls: Mapping[UUID, PollOutcome]
    presence: Mapping[UUID, Present]
    guests_by_meeting: Mapping[UUID, int]
    late_guests: Mapping[UUID, int]
    voters: Mapping[UUID, int]
    own: Mapping[UUID, MyBallot]
    represented: frozenset[UUID]
    for_principal: bool


def _grouped(rows: Sequence[Any]) -> dict[Any, list[Any]]:
    """Group `(key, value)` rows by key; the values keep their order within a key."""
    ordered = sorted(rows, key=lambda row: row[0])
    return {
        key: [value for _, value in group] for key, group in groupby(ordered, key=lambda r: r[0])
    }


def _aggregates(
    vote: Vote, tally: _Tally, election: ElectionOutcome | None, poll: PollOutcome | None
) -> _Aggregates:
    """Return the display aggregates: a poll or an election replaces the plain tally."""
    counts, leading, reason = tally
    match (election, poll):
        case (_, PollOutcome()):
            return poll.display_counts(), None, poll.ballots, None
        case (ElectionOutcome(), None):
            failed = "quorum" if vote.status == "closed" and not election.quorum_met else None
            return election.display_counts(), None, election.ballots, failed
        case _:
            return counts, leading, sum((counts or {}).values()), reason


def _meeting_vote_out(vote: Vote, meeting_id: UUID, reads: _VoteReads) -> MeetingVoteOut:
    """Build one vote of the reload path from the batched reads."""
    config = VoteConfig.from_stored(vote.config)
    poll = reads.polls.get(vote.id)
    counts, leading, voted, reason = _aggregates(
        vote, reads.tallies.get(vote.id, _NO_TALLY), reads.elections.get(vote.id), poll
    )
    settled = vote.status in ("closed", "cancelled")
    here = reads.presence.get(meeting_id, NOBODY)
    members: int | None = getattr(vote, "present_members", None) if settled else here.members
    stored_guests: int | None = (
        getattr(vote, "present_guests", None)
        if settled
        else reads.guests_by_meeting.get(meeting_id, 0)
    )
    with_guests = config.guests_vote and not settled
    late = reads.late_guests.get(vote.id, 0)
    guests = (stored_guests or 0) + late if with_guests else stored_guests
    present = (
        here.total + reads.guests_by_meeting.get(meeting_id, 0) + late
        if with_guests
        else here.total
    )
    revealed = vote.status == "closed"
    running = vote.status == "open"
    voted_now = reads.voters.get(vote.id, 0) if running else voted
    return MeetingVoteOut(
        id=vote.id,
        applicationId=vote.application_id,
        agendaItemId=vote.agenda_item_id,
        question=vote.question,
        options=list(config.options),
        status=vote.status,  # type: ignore[arg-type]
        result=vote.result,
        counts=counts if revealed else {},
        leading=leading if revealed else None,
        voted=voted_now,
        present=max(present, voted_now) if running else present,
        revealed=revealed,
        failedReason=reason,
        majorityRule=config.majority_rule,
        secret=config.secret,
        quorum=config.quorum,
        openedAt=vote.opens_at,
        closedAt=vote.closed_at,
        myBallot=reads.own.get(vote.id, MyBallot()) if reads.for_principal else None,
        representedCast=vote.id in reads.represented,
        guestsVote=config.guests_vote,
        presentMembers=members,
        presentGuests=guests,
        proposal=DecisionIn.from_stored(getattr(vote, "proposal", None)),
        repeatOfId=getattr(vote, "repeat_of_id", None),
        attempt=getattr(vote, "attempt", 1) or 1,
        **election_fields(vote),
        **poll_fields(vote, result_of(poll) if poll is not None and revealed else None),
    )


def _counts_present(vote: Vote) -> bool:
    """Tell if the quorum of a meeting vote counts the present members."""
    stored = vote.config if isinstance(vote.config, dict) else {}
    return vote.meeting_id is not None and stored.get("quorumBasis") == "present"


def _quorum_present(vote: Vote, presence: Mapping[UUID, Present]) -> int | None:
    """Return the present count for the quorum of a meeting vote, or None.

    Only a vote with ``quorumBasis = present`` has one: the present members plus the
    pool substitutes on a seat. A closed vote takes the members and the seats fixed at
    its close, a running vote the present count of its meeting now.
    """
    if vote.meeting_id is None or not _counts_present(vote):
        return None
    closed = vote.status == "closed"
    fixed: int | None = getattr(vote, "present_members", None) if closed else None
    seats: int | None = getattr(vote, "present_seats", None) if closed else None
    here = presence.get(vote.meeting_id, NOBODY)
    return (here.members if fixed is None else fixed) + (here.seats if seats is None else seats)


def _reload_tally(vote: Vote, choices: list[str | None], present: int | None) -> _Tally:
    """Tally one vote from its stored choices; the failed reason only for a closed result."""
    from app.modules.voting import tally as tally_mod

    config = VoteConfig.from_stored(vote.config)
    counts = tally_mod.tally(config.options, choices)
    outcome = tally_mod.result(config, counts, vote.eligible_count or 0, present=present)
    reason: Literal["quorum", "majority"] | None = (
        tally_mod.failed_reason(outcome.result, outcome.quorum_met)
        if vote.status == "closed" and vote.result is not None
        else None
    )
    return dict(counts), outcome.leading, reason


class VoteReadOps(MeetingServiceBase):
    """Reload-path vote aggregation and vote-related lookup helpers."""

    async def _votes_for(
        self, meeting_ids: list[UUID], principal: Principal | None = None
    ) -> dict[UUID, list[MeetingVoteOut]]:
        """Return the votes bound to the meetings, grouped per `meeting_id`.

        With a `principal` each vote carries `myBallot` and `representedCast` for that
        caller. Without one (a broadcast) both stay empty.

        Rebuild the counts, the leading option and the failed reason per vote from the
        ballots. This is the reload path; the live WebSocket path already carries these
        values. One batched query keeps this free of N+1. An election counts ballots and
        candidates (`tally_election`), a poll only counts (`tally_poll`).

        A vote with guests expects the ballots of the admitted guests too, and counts the
        guests who voted and left since then. A closed vote shows the attendance fixed at
        the close; a cancelled vote and an older closed vote have none.

        The reveal rule matches the voting service: only a closed vote reveals. Every
        vote is secret, so in every other case the counts and the leading option stay
        hidden, to prevent an interim leak.
        """
        if not meeting_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(Vote).where(Vote.meeting_id.in_(meeting_ids)).order_by(Vote.created_at)
                )
            )
            .scalars()
            .all()
        )
        presence = await present_mod.present_counts(self.session, meeting_ids)
        tallies = await self._vote_tallies(rows, presence)
        elections = await self._election_tallies([v for v in rows if is_election(v)], presence)
        polls = await self._poll_tallies([v for v in rows if is_poll(v)])
        guests_by_meeting = await self.admitted_guests_by_meeting(meeting_ids)
        guest_votes = [
            v.id
            for v in rows
            if v.status not in ("closed", "cancelled")
            and bool((v.config if isinstance(v.config, dict) else {}).get("guestsVote"))
        ]
        late_guests = await self._departed_guest_voters(guest_votes) if guest_votes else {}
        own, represented = (
            await self._ballots_of(principal.sub, rows)
            if principal is not None and rows
            else ({}, set[UUID]())
        )
        reads = _VoteReads(
            tallies=tallies,
            elections=elections,
            polls=polls,
            presence=presence,
            guests_by_meeting=guests_by_meeting,
            late_guests=late_guests,
            voters=await self._voters_by_vote([v.id for v in rows if v.status == "open"]),
            own=own,
            represented=frozenset(represented),
            for_principal=principal is not None,
        )
        outs = [
            (v.meeting_id, _meeting_vote_out(v, v.meeting_id, reads))
            for v in rows
            if v.meeting_id is not None
        ]
        return {
            meeting_id: [out for owner, out in outs if owner == meeting_id]
            for meeting_id in dict.fromkeys(meeting_id for meeting_id, _ in outs)
        }

    async def _choices_by_vote(self, votes: Sequence[Vote]) -> dict[UUID, list[str | None]]:
        """Load the stored choices of the votes from ``secret_ballot`` in one query."""
        rows = (
            await self.session.execute(
                select(SecretBallot.vote_id, SecretBallot.choice).where(
                    SecretBallot.vote_id.in_([v.id for v in votes])
                )
            )
        ).all()
        return _grouped(rows)

    async def _poll_tallies(self, votes: Sequence[Vote]) -> dict[UUID, PollOutcome]:
        """Tally the polls of the reload path in one query."""
        if not votes:
            return {}
        choices = await self._choices_by_vote(votes)
        return {v.id: tally_poll(choices.get(v.id, []), poll_config(v)) for v in votes}

    async def _election_tallies(
        self, votes: Sequence[Vote], presence: Mapping[UUID, Present]
    ) -> dict[UUID, ElectionOutcome]:
        """Tally the elections of the reload path in one query."""
        if not votes:
            return {}
        choices = await self._choices_by_vote(votes)
        return {
            v.id: tally_election(
                choices.get(v.id, []),
                election_config(v),
                v.eligible_count or 0,
                round_=getattr(v, "round", 1) or 1,
                present=_quorum_present(v, presence),
            )
            for v in votes
        }

    async def assert_candidates_exist(self, principal_ids: list[UUID]) -> None:
        """Check that every account of an election candidate exists.

        Raises:
            ValidationProblem: An account is unknown (``candidate_unknown``).
        """
        if not principal_ids:
            return
        found = set(
            (
                await self.session.execute(
                    select(PrincipalRow.id).where(PrincipalRow.id.in_(principal_ids))
                )
            )
            .scalars()
            .all()
        )
        if set(principal_ids) - found:
            raise ValidationProblem(
                "A candidate account does not exist.",
                code="candidate_unknown",
                errors=[{"field": "candidates", "msg": "unknown principalId"}],
            )

    async def _ballots_of(
        self, sub: str, votes: Sequence[Vote]
    ) -> tuple[dict[UUID, MyBallot], set[UUID]]:
        """Return the own ballots of `sub` and the votes with a represented ballot.

        The own ballot gives only `cast` from the voted marker, because the choice has
        no link to the voter. A represented ballot runs under the `sub` of a
        delegator: each voting delegation of this meeting and gremium where `sub` is
        the delegate. A vote counts as represented when every delegator has a ballot.
        An election counts them only with the gremium switch `delegation_in_elections`.
        One batched query per table keeps this free of N+1.
        """
        ids = [v.id for v in votes]
        meeting_ids = {v.meeting_id for v in votes if v.meeting_id is not None}
        delegate = aliased(PrincipalRow)
        delegator = aliased(PrincipalRow)
        deleg_rows = (
            await self.session.execute(
                select(MeetingDelegation.meeting_id, MeetingDelegation.gremium_id, delegator.sub)
                .join(delegate, delegate.id == MeetingDelegation.delegate_principal_id)
                .join(delegator, delegator.id == MeetingDelegation.delegator_principal_id)
                .where(
                    delegate.sub == sub,
                    MeetingDelegation.meeting_id.in_(meeting_ids),
                    MeetingDelegation.delegate_voting.is_(True),
                )
            )
        ).all()
        delegators = {
            key: {d_sub for mid, gid, d_sub in deleg_rows if (mid, str(gid)) == key}
            for key in {(mid, str(gid)) for mid, gid, _sub in deleg_rows}
        }
        in_elections = await self._gremien_with_election_delegation(
            {gid for _mid, gid, _sub in deleg_rows} if any(map(is_election, votes)) else set()
        )
        subs = {sub, *(d for group in delegators.values() for d in group)}
        markers = {
            (vid, voter)
            for vid, voter in (
                await self.session.execute(
                    select(VotedMarker.vote_id, VotedMarker.voter_sub).where(
                        VotedMarker.vote_id.in_(ids), VotedMarker.voter_sub.in_(subs)
                    )
                )
            ).all()
        }

        own = {v.id: MyBallot(cast=True) for v in votes if (v.id, sub) in markers}
        by_vote = {
            v.id: delegators.get((v.meeting_id, v.eligible_group), set())
            for v in votes
            if v.meeting_id is not None and (not is_election(v) or v.eligible_group in in_elections)
        }
        represented = {
            vid
            for vid, group in by_vote.items()
            if group and all((vid, d_sub) in markers for d_sub in group)
        }
        return own, represented

    async def _gremien_with_election_delegation(self, gremium_ids: set[UUID]) -> set[str]:
        """Return the ids, as text, of the Gremien that take delegation ballots in elections."""
        if not gremium_ids:
            return set()
        rows = await self.session.scalars(
            select(Gremium.id).where(
                Gremium.id.in_(gremium_ids), Gremium.delegation_in_elections.is_(True)
            )
        )
        return {str(gid) for gid in rows.all()}

    async def _voters_by_vote(self, vote_ids: list[UUID]) -> dict[UUID, int]:
        """Return `{vote_id: number of persons who cast}` (§F/meetings/voting/000933).

        One cast counts once: a ballot with `same_caster` belongs to a person who is
        counted already.
        """
        if not vote_ids:
            return {}
        rows = (
            await self.session.execute(
                select(VotedMarker.vote_id, func.count())
                .where(VotedMarker.vote_id.in_(vote_ids), VotedMarker.same_caster.is_(False))
                .group_by(VotedMarker.vote_id)
            )
        ).all()
        return dict(rows)

    async def _departed_guest_voters(self, vote_ids: list[UUID]) -> dict[UUID, int]:
        """Count per vote the guests with a ballot who are no longer admitted."""
        from app.modules.voting.service import GUEST_VOTER_PREFIX

        admitted = {
            f"{GUEST_VOTER_PREFIX}{gid}"
            for gid in (
                await self.session.execute(
                    select(MeetingGuest.id)
                    .join(Vote, Vote.meeting_id == MeetingGuest.meeting_id)
                    .where(Vote.id.in_(vote_ids), MeetingGuest.status == "admitted")
                )
            )
            .scalars()
            .all()
        }
        markers = (
            await self.session.execute(
                select(VotedMarker.vote_id, VotedMarker.voter_sub).where(
                    VotedMarker.vote_id.in_(vote_ids),
                    VotedMarker.voter_sub.startswith(GUEST_VOTER_PREFIX),
                )
            )
        ).all()
        return {vid: len(set(subs) - admitted) for vid, subs in _grouped(markers).items()}

    async def admitted_guests_by_meeting(self, meeting_ids: list[UUID]) -> dict[UUID, int]:
        """Return `{meeting_id: number of admitted guests}`."""
        if not meeting_ids:
            return {}
        rows = (
            await self.session.execute(
                select(MeetingGuest.meeting_id, func.count())
                .where(
                    MeetingGuest.meeting_id.in_(meeting_ids),
                    MeetingGuest.status == "admitted",
                )
                .group_by(MeetingGuest.meeting_id)
            )
        ).all()
        return dict(rows)

    async def _vote_tallies(
        self, votes: Sequence[Vote], presence: Mapping[UUID, Present]
    ) -> dict[UUID, _Tally]:
        """Build `{vote_id: (counts, leading, failedReason)}` from the ballots.

        This is the reload path. The method loads the ballots from `secret_ballot` in
        one batch and then applies the pure tally logic. It sets `failedReason` for
        closed, failed votes only.
        """
        if not votes:
            return {}
        by_vote = await self._choices_by_vote(votes)
        return {
            v.id: _reload_tally(v, by_vote.get(v.id, []), _quorum_present(v, presence))
            for v in votes
        }

    async def open_vote(self, meeting_id: UUID) -> Vote | None:
        """Return the open vote of this meeting for the `subscribe` reconnect state."""
        return (
            await self.session.execute(
                select(Vote)
                .where(Vote.meeting_id == meeting_id, Vote.status == "open")
                .order_by(Vote.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def agenda_item_has_vote(self, item_id: UUID) -> bool:
        """Tell if this agenda item already has a vote that is not cancelled.

        An application agenda item accepts one vote at most. A cancelled vote does not
        count. Without this rule, a once-cancelled application vote would block every
        later vote on the same agenda item.
        """
        return (
            await self.session.execute(
                select(Vote.id)
                .where(Vote.agenda_item_id == item_id, Vote.status != "cancelled")
                .limit(1)
            )
        ).first() is not None

    async def application_state_kind(self, application_id: UUID) -> str | None:
        """Return the `state.kind` of the current application state, or `None`."""
        from app.modules.applications.models import Application
        from app.modules.flow.models import State

        return await self.session.scalar(
            select(State.kind)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )

    async def application_vote_gremium(self, application_id: UUID) -> UUID | None:
        """Return the Gremium that decides the current vote state (the snapshot)."""
        from app.modules.applications.models import Application

        return await self.session.scalar(
            select(Application.vote_gremium_id).where(Application.id == application_id)
        )

    async def gremium_quorum_min_present(self, gremium_id: UUID) -> int | None:
        """Return the least number of present roster persons of this gremium, or None."""
        return (
            await self.session.execute(
                select(Gremium.quorum_min_present).where(Gremium.id == gremium_id)
            )
        ).scalar_one_or_none()

    async def gremium_repeat_quorum_percent(self, gremium_id: UUID) -> int | None:
        """Return the quorum of a Wiederholungssitzung of this gremium in percent, or None."""
        return (
            await self.session.execute(
                select(Gremium.repeat_quorum_percent).where(Gremium.id == gremium_id)
            )
        ).scalar_one_or_none()

    async def gremium_quorum_percent(self, gremium_id: UUID) -> int | None:
        """Return the default quorum of this gremium in percent of eligible voters.

        A result of `None` means the gremium sets no default quorum.
        """
        return (
            await self.session.execute(
                select(Gremium.quorum_percent).where(Gremium.id == gremium_id)
            )
        ).scalar_one_or_none()

    async def present_member_count(self, meeting_id: UUID) -> int:
        """Return the present members of the meeting (the base of a guest vote)."""
        return (await present_count(self.session, meeting_id)).members
