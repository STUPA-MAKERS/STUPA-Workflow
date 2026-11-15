"""The cast of a ballot: own, for a represented member and of a guest."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, exists
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.delegations.pool_seat import (
    claim_pool_seat,
    pool_seat_for,
    release_pool_seat_of,
)
from app.modules.delegations.service import Represented, voting_delegation_check
from app.modules.voting import election as election_mod
from app.modules.voting import poll as poll_mod
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.voting.schemas import BallotAccepted
from app.modules.voting.service.access import VoteAccessOps
from app.modules.voting.service.base import (
    ALREADY_VOTED,
    Choice,
    guest_voter_sub,
)
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem


class VoteCastOps(VoteAccessOps):
    """The cast of a ballot: own, for a represented member and of a guest."""

    async def cast(
        self,
        vote_id: UUID,
        principal: Principal,
        choice: Choice,
        *,
        now: datetime,
        as_delegation: bool = False,
    ) -> BallotAccepted:
        """Cast a vote.

        One cast counts for the own ballot and for every member that the principal
        represents: it writes one ballot for the principal and one under the ``sub`` of
        each delegator, all with the same choice. This is a transfer, not a duplicate.
        The unique constraint on (vote, voter) protects each ballot on its own, and a
        represented ballot that is already in stays as it is.

        ``as_delegation=True`` casts the represented ballots alone. It is the cast of a
        person without an own ballot (an external delegate, a pool substitute) and of a
        member whose own ballot is already in. While the own ballot is open and the
        member holds a delegation, it answers 409 ``vote_as_unit``: two casts could
        differ, and a secret ballot has no link to its voter.

        An election takes the ballot of a delegation only with the gremium switch
        ``delegation_in_elections``. Without it the own cast writes the own ballot
        alone, and the represented cast answers 403 ``delegation_not_in_election``. A
        pool seat counts in every vote.

        The row lock serializes this call against ``close``. The status check and the
        ballot inserts share one transaction, so no ballot lands after the tally.

        Voting stays human, so a principal with a scope cap gets 403. ``vote.cast`` sits
        in FORBIDDEN_PERMISSIONS, so no OAuth scope carries it. The group keys carry no
        scope cap, and the delegated ballot reads no permission at all, so the rule
        stands here for both ballots.

        The own ballot checks the roster of the vote, because the router gates only the
        session and external substitutes reach this point. Each represented ballot
        audits the use of the delegation. A member who casts the own ballot in a meeting
        takes part in the meeting, which frees a pool seat of the member
        (``release_pool_seat_of``).

        A pool substitute without a voting delegation claims a free seat with the
        represented cast (``claim_pool_seat``). The claim stores a delegation, so the
        ballot runs under the ``sub`` of the represented member like any delegated
        ballot, and a refused ballot rolls the claim back.

        Raises:
            ConflictError: 409 - the vote is closed, the voter already voted, or the
                represented cast must be the own cast (``vote_as_unit``).
            ForbiddenError: 403 - the voter is not eligible for this vote.
            ValidationProblem: 422 - the choice is not a configured option.
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="vote_not_open")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="vote_window_closed")
        if principal.scope_permissions is not None:
            raise ForbiddenError("Only a human session can cast a ballot.")
        blocked, incoming = await voting_delegation_check(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group, now
        )
        represented = await self._represented_in(vote, incoming)
        own = None if as_delegation else self._own_voter(principal, vote, blocked=blocked)
        others = (
            await self._represented_voters(
                principal,
                vote,
                represented,
                own_open=await self._own_open(principal, vote, blocked=blocked),
                refused=len(represented) < len(incoming),
            )
            if as_delegation
            else [r.sub for r in represented]
        )
        config = self._config(vote)
        stored = self._stored_choice(vote, config, choice)
        if own is not None and not await self._insert_ballot(vote.id, own, stored):
            raise ConflictError("Already voted.", code=ALREADY_VOTED)
        seen = self._has_marker(vote.id, principal.sub)
        written = [
            sub
            for index, sub in enumerate(others)
            if await self._insert_ballot(
                vote.id, sub, stored, same_caster=own is not None or index > 0 or seen
            )
        ]
        if own is None and not written:
            raise ConflictError("Already voted.", code=ALREADY_VOTED)
        for _ in written:
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.DELEGATION_USE,
                target_type="vote",
                target_id=str(vote.id),
                data={"eligibleGroup": vote.eligible_group},
            )
        if vote.meeting_id is not None and own is not None:
            from app.modules.meetings.attendance_service import AttendanceService

            await release_pool_seat_of(self.session, vote.meeting_id, principal.sub)
            await AttendanceService(self.session).mark_present_on_cast(
                vote.meeting_id, principal.sub
            )
        return await self._accept(len(written) + (own is not None))

    async def _accept(self, ballots: int) -> BallotAccepted:
        """Commit the ballots of one cast and build the answer."""
        await self.session.commit()
        return BallotAccepted(status="cast", ballots=ballots)

    async def _own_open(self, principal: Principal, vote: Vote, *, blocked: bool) -> bool:
        """Tell whether the principal can still cast an own ballot in ``vote``."""
        return (
            not blocked
            and self._may_cast(principal, vote.eligible_group)
            and not (await self.my_ballot(vote, principal.sub)).cast
        )

    async def _represented_voters(
        self,
        principal: Principal,
        vote: Vote,
        represented: tuple[Represented, ...],
        *,
        own_open: bool,
        refused: bool,
    ) -> list[str]:
        """Return each ``sub`` that a represented cast writes a ballot under.

        Without a voting delegation, a pool substitute claims a free seat
        (``claim_pool_seat``).

        Raises:
            ConflictError: 409 ``vote_as_unit`` - the own ballot is open, and the own
                cast counts for the represented members too.
            ForbiddenError: 403 - neither a delegation nor a free seat, or an election
                that takes no delegation ballot (``delegation_not_in_election``).
        """
        if represented:
            if own_open:
                raise ConflictError(
                    "Cast the own ballot. It counts for the represented members too.",
                    code="vote_as_unit",
                )
            return [r.sub for r in represented]
        if refused:
            raise ForbiddenError(
                "An election takes no delegation ballot.", code="delegation_not_in_election"
            )
        seat = await claim_pool_seat(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group
        )
        if seat is None:
            raise ForbiddenError("No delegated voting right for this ballot.")
        return [seat]

    def _own_voter(self, principal: Principal, vote: Vote, *, blocked: bool) -> str:
        """Return the ``sub`` of an own ballot after the roster check.

        Raises:
            ForbiddenError: 403 - the right is delegated away, or the principal is not
                on the roster of the vote.
        """
        if blocked:
            raise ForbiddenError("Voting right has been delegated to another member.")
        if not self._may_cast(principal, vote.eligible_group):
            raise ForbiddenError("Not eligible to vote in this ballot.")
        return principal.sub

    @staticmethod
    def _stored_choice(vote: Vote, config: VoteConfig, choice: Choice) -> str:
        """Check a ballot against the vote and return its stored form.

        A motion takes one configured option. An election and a poll take their
        own ballot shape (``election.stored_choice``, ``poll.stored_choice``).

        Raises:
            ValidationProblem: The choice does not fit the vote (422).
        """
        if poll_mod.is_poll(vote):
            return poll_mod.stored_choice(poll_mod.poll_config(vote), choice)
        if isinstance(choice, Mapping):
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        if election_mod.is_election(vote):
            return election_mod.stored_choice(election_mod.election_config(vote), choice)
        if not isinstance(choice, str) or choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        return choice

    async def cast_guest(
        self, vote_id: UUID, guest_id: UUID, choice: Choice, *, now: datetime
    ) -> BallotAccepted:
        """Cast the ballot of an admitted guest of a public meeting.

        This is the second, separate eligibility path of ``cast``. A guest is not a
        principal: no ``vote.cast``, no gremium role and no delegation. The caller (the
        public guest service) checks that the guest is admitted, that the meeting lets
        guests vote, and that the vote belongs to a public agenda item of the meeting
        of the guest. This method checks the vote itself: open, in its window, and
        ``guestsVote``. The ballot runs under ``guest:<id>``. The same rules as for a
        member apply: one ballot, never changed after the cast, and the vote keeps
        the identity (``voted_marker``) apart from the choice (``secret_ballot``).
        The audit entry ``vote_cast`` names the guest id as the actor and carries no
        choice.

        The audit entry carries ids only, because a secret vote must not link a choice
        to the guest and the chain is append-only.

        Raises:
            ConflictError: 409 - the vote is not open, or the guest already voted.
            ForbiddenError: 403 - the vote is for members only (``vote_members_only``).
            ValidationProblem: 422 - the choice is not a configured option.
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="vote_not_open")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="vote_window_closed")
        config = self._config(vote)
        if not config.guests_vote:
            raise ForbiddenError("Only the members vote in this ballot.", code="vote_members_only")
        stored = self._stored_choice(vote, config, choice)
        voter_sub = guest_voter_sub(guest_id)
        await audit_record(
            self.session,
            actor=voter_sub,
            action=AuditAction.VOTE_CAST,
            target_type="vote",
            target_id=str(vote.id),
            data=self._audit_refs(vote),
        )
        if not await self._insert_ballot(vote.id, voter_sub, stored):
            raise ConflictError("Already voted.", code=ALREADY_VOTED)
        return await self._accept(1)

    async def can_still_cast(self, vote: Vote, principal: Principal, *, now: datetime) -> bool:
        """Tell whether `cast` takes a ballot of the principal now, own or represented.

        The rule mirrors the gate of `cast` without a write: the vote is open and its
        window has not ended, the session is human (no OAuth token), and either the
        own ballot (``vote.cast`` in the gremium of the vote, the right not delegated
        away) or the represented ballot (a voting delegation for the meeting, or a free
        pool seat that ``cast`` would claim) is still missing. A ballot that is already
        in counts as done, because `cast` answers 409 for it. The task list
        (`ListingOps.list_tasks`) reads this method.
        """
        if vote.status != "open":
            return False
        if vote.closes_at is not None and now >= vote.closes_at:
            return False
        if principal.scope_permissions is not None:
            return False
        blocked, incoming = await voting_delegation_check(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group, now
        )
        if await self._own_open(principal, vote, blocked=blocked):
            return True
        if incoming:
            return not await self._all_cast(vote, await self._represented_in(vote, incoming))
        seat = await self._free_seat_sub(principal, vote)
        return seat is not None and not (await self.my_ballot(vote, seat)).cast

    async def _free_seat_sub(self, principal: Principal, vote: Vote) -> str | None:
        """Return the ``sub`` of the pool seat that the principal could claim, or None."""
        seat = await pool_seat_for(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group
        )
        return seat.sub if seat is not None else None

    @staticmethod
    def _has_marker(vote_id: UUID, voter_sub: str) -> ColumnElement[bool]:
        """Build the SQL test "this voter has a ballot in the vote".

        The represented cast of a person whose own ballot is in counts no second person.
        The test runs inside the insert, so it costs no read.
        """
        marker = aliased(VotedMarker)
        return exists().where(marker.vote_id == vote_id, marker.voter_sub == voter_sub)

    async def _insert_ballot(
        self,
        vote_id: UUID,
        voter_sub: str,
        choice: str,
        *,
        same_caster: bool | ColumnElement[bool] = False,
    ) -> bool:
        """Insert the secret ballot of one voter. Return False when the voter already voted.

        ``same_caster`` marks a ballot whose caster already has a counted ballot in the
        vote. The turnout of a running vote leaves it out (``voters``).

        ``voted_marker`` (UNIQUE) is the "has voted" identity anchor. The method writes
        the identity-less ballot only when the marker is new, so no link from choice to
        voter exists. ``ON CONFLICT DO NOTHING`` keeps the first marker, and an empty
        ``RETURNING`` means the voter already voted. The method does not commit: the
        ballots of one cast share the transaction of ``cast``.
        """
        marker = (
            pg_insert(VotedMarker)
            .values(vote_id=vote_id, voter_sub=voter_sub, same_caster=same_caster)
            .on_conflict_do_nothing(constraint="uq_voted_marker_vote_voter")
            .returning(VotedMarker.id)
        )
        if (await self.session.execute(marker)).first() is None:
            return False
        self.session.add(SecretBallot(vote_id=vote_id, choice=choice))
        return True
