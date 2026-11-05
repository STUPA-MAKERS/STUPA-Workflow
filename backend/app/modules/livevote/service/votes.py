"""Meeting-bound vote reads: tally reload, reveal rule, and quorum helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.modules.admin.gremium_roles import membership_active_clause
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.applications.decision import DecisionIn
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.livevote.models import MeetingAttendance, MeetingGuest
from app.modules.livevote.schemas import MeetingVoteOut
from app.modules.livevote.service.service_base import MeetingServiceBase
from app.modules.voting.election import election_config, election_fields, is_election
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.voting.poll import is_poll, poll_config, poll_fields, result_of
from app.modules.voting.schemas import MyBallot
from app.modules.voting.tally import ElectionOutcome, PollOutcome, tally_election, tally_poll
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ValidationProblem


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
        tallies = await self._vote_tallies(rows)
        elections = await self._election_tallies([v for v in rows if is_election(v)])
        polls = await self._poll_tallies([v for v in rows if is_poll(v)])
        present_by_meeting = await self._present_by_meeting(meeting_ids)
        guests_by_meeting = await self.admitted_guests_by_meeting(meeting_ids)
        guest_votes = [
            v.id
            for v in rows
            if v.status not in ("closed", "cancelled")
            and bool((v.config if isinstance(v.config, dict) else {}).get("guestsVote"))
        ]
        late_guests = await self._departed_guest_voters(guest_votes) if guest_votes else {}
        own: dict[UUID, MyBallot] = {}
        represented: set[UUID] = set()
        if principal is not None and rows:
            own, represented = await self._ballots_of(principal.sub, rows)
        out: dict[UUID, list[MeetingVoteOut]] = {}
        for v in rows:
            if v.meeting_id is None:
                continue
            config = VoteConfig.from_stored(v.config)
            opts = config.options
            counts, leading, reason = tallies.get(v.id, (None, None, None))
            voted = sum((counts or {}).values())
            ev = elections.get(v.id)
            if ev is not None:
                counts, leading, voted = ev.display_counts(), None, ev.ballots
                reason = "quorum" if v.status == "closed" and not ev.quorum_met else None
            pv = polls.get(v.id)
            if pv is not None:
                counts, leading, voted, reason = pv.display_counts(), None, pv.ballots, None
            members: int | None
            guests: int | None
            if v.status in ("closed", "cancelled"):
                members = getattr(v, "present_members", None)
                guests = getattr(v, "present_guests", None)
            else:
                members = present_by_meeting.get(v.meeting_id, 0)
                guests = guests_by_meeting.get(v.meeting_id, 0)
            present = present_by_meeting.get(v.meeting_id, 0)
            if config.guests_vote and v.status not in ("closed", "cancelled"):
                extra = late_guests.get(v.id, 0)
                guests = (guests or 0) + extra
                present += guests_by_meeting.get(v.meeting_id, 0) + extra
            revealed = v.status == "closed"
            out.setdefault(v.meeting_id, []).append(
                MeetingVoteOut(
                    id=v.id,
                    applicationId=v.application_id,
                    agendaItemId=v.agenda_item_id,
                    question=v.question,
                    options=list(opts),
                    status=v.status,  # type: ignore[arg-type]
                    result=v.result,
                    counts=counts if revealed else {},
                    leading=leading if revealed else None,
                    voted=voted,
                    present=present,
                    revealed=revealed,
                    failedReason=reason,
                    majorityRule=config.majority_rule,
                    secret=config.secret,
                    quorum=config.quorum,
                    openedAt=v.opens_at,
                    closedAt=v.closed_at,
                    myBallot=own.get(v.id, MyBallot()) if principal is not None else None,
                    representedCast=v.id in represented,
                    guestsVote=config.guests_vote,
                    presentMembers=members,
                    presentGuests=guests,
                    proposal=DecisionIn.from_stored(getattr(v, "proposal", None)),
                    repeatOfId=getattr(v, "repeat_of_id", None),
                    attempt=getattr(v, "attempt", 1) or 1,
                    **election_fields(v),
                    **poll_fields(
                        v,
                        result_of(pv) if pv is not None and revealed else None,
                    ),
                )
            )
        return out

    async def _choices_by_vote(self, votes: Sequence[Vote]) -> dict[UUID, list[str | None]]:
        """Load the stored choices of the votes from ``secret_ballot`` in one query."""
        choices: dict[UUID, list[str | None]] = {}
        for vid, choice in (
            await self.session.execute(
                select(SecretBallot.vote_id, SecretBallot.choice).where(
                    SecretBallot.vote_id.in_([v.id for v in votes])
                )
            )
        ).all():
            choices.setdefault(vid, []).append(choice)
        return choices

    async def _poll_tallies(self, votes: Sequence[Vote]) -> dict[UUID, PollOutcome]:
        """Tally the polls of the reload path in one query."""
        if not votes:
            return {}
        choices = await self._choices_by_vote(votes)
        return {v.id: tally_poll(choices.get(v.id, []), poll_config(v)) for v in votes}

    async def _election_tallies(self, votes: Sequence[Vote]) -> dict[UUID, ElectionOutcome]:
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
        no link to the voter. A represented ballot runs under the `sub` of the
        delegator: the active voting delegation of this meeting and gremium, where
        `sub` is the delegate. One batched query per table keeps this free of N+1.
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
        delegator_of = {(mid, str(gid)): d_sub for mid, gid, d_sub in deleg_rows}
        subs = {sub, *delegator_of.values()}
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

        own: dict[UUID, MyBallot] = {}
        represented: set[UUID] = set()
        for v in votes:
            if (v.id, sub) in markers:
                own[v.id] = MyBallot(cast=True)
            d_sub = delegator_of.get((v.meeting_id, v.eligible_group)) if v.meeting_id else None
            if d_sub is not None and (v.id, d_sub) in markers:
                represented.add(v.id)
        return own, represented

    async def _present_by_meeting(self, meeting_ids: list[UUID]) -> dict[UUID, int]:
        """Return `{meeting_id: number of present members}`."""
        if not meeting_ids:
            return {}
        rows = (
            await self.session.execute(
                select(MeetingAttendance.meeting_id, func.count())
                .where(
                    MeetingAttendance.meeting_id.in_(meeting_ids),
                    MeetingAttendance.status == "present",
                )
                .group_by(MeetingAttendance.meeting_id)
            )
        ).all()
        return {mid: n for mid, n in rows}

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
        voters: dict[UUID, set[str]] = {}
        for vid, sub in (
            await self.session.execute(
                select(VotedMarker.vote_id, VotedMarker.voter_sub).where(
                    VotedMarker.vote_id.in_(vote_ids),
                    VotedMarker.voter_sub.startswith(GUEST_VOTER_PREFIX),
                )
            )
        ).all():
            voters.setdefault(vid, set()).add(sub)
        return {vid: len(subs - admitted) for vid, subs in voters.items()}

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
        return {mid: n for mid, n in rows}

    async def _vote_tallies(
        self, votes: Sequence[Vote]
    ) -> dict[
        UUID,
        tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None],
    ]:
        """Build `{vote_id: (counts, leading, failedReason)}` from the ballots.

        This is the reload path. The method loads the ballots from `secret_ballot` in
        one batch and then applies the pure tally logic. It sets `failedReason` for
        closed, failed votes only.
        """
        from app.modules.voting import tally as tally_mod

        if not votes:
            return {}
        by_vote = await self._choices_by_vote(votes)
        out: dict[
            UUID,
            tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None],
        ] = {}
        for v in votes:
            config = VoteConfig.from_stored(v.config)
            counts = tally_mod.tally(config.options, by_vote.get(v.id, []))
            outcome = tally_mod.result(config, counts, v.eligible_count or 0)
            reason: Literal["quorum", "majority"] | None = None
            if v.status == "closed" and v.result is not None:
                reason = tally_mod.failed_reason(outcome.result, outcome.quorum_met)
            out[v.id] = (dict(counts), outcome.leading, reason)
        return out

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
        return (await self._present_by_meeting([meeting_id])).get(meeting_id, 0)

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        """Return the roster size for the quorum: active members with a `vote.cast` role."""
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(GremiumMembership.principal_id, GremiumRole.permissions)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.gremium_id == gremium_id,
                    membership_active_clause(now),
                )
            )
        ).all()
        return len({pid for pid, perms in rows if "vote.cast" in (perms or [])})
