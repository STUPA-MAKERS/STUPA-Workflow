"""The reads of a vote and the rights to read, cast and manage it."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import func, select

from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.delegations.service import Represented, counted_in, voting_delegation_check
from app.modules.voting import circular as circular_mod
from app.modules.voting import election as election_mod
from app.modules.voting import poll as poll_mod
from app.modules.voting.models import Vote, VotedMarker
from app.modules.voting.schemas import (
    CancelReason,
    MyBallot,
    VoteKind,
    VoteListItem,
    VoteOut,
    VoteStatus,
)
from app.shared.errors import ForbiddenError
from app.shared.paging import DEFAULT_LIMIT, Page

if TYPE_CHECKING:
    from app.modules.voting.service.service import VotingService

from app.modules.voting.service.base import (
    VotingServiceBase,
    _with_stored_result,
    holds_gremium_vote_role,
    manages_votes_in_gremium,
)


class VoteAccessOps(VotingServiceBase):
    """The reads of a vote and the rights to read, cast and manage it."""

    async def _represented_in(
        self, vote: Vote, incoming: tuple[Represented, ...]
    ) -> tuple[Represented, ...]:
        """Return the represented members that a cast in ``vote`` writes a ballot for.

        An election reads the gremium switch ``delegation_in_elections``
        (``counted_in``). Every other vote counts all of them without a read.
        """
        if not incoming or not election_mod.is_election(vote):
            return incoming
        from app.modules.gremien.models import Gremium

        gremium_id = await self._vote_gremium_id(
            meeting_id=vote.meeting_id, eligible_group=vote.eligible_group
        )
        in_elections = gremium_id is not None and await self.session.scalar(
            select(Gremium.delegation_in_elections).where(Gremium.id == gremium_id)
        )
        return counted_in(vote, incoming, in_elections=bool(in_elections))

    @staticmethod
    def _is_gremium_group(eligible_group: str) -> bool:
        """Tell whether ``eligible_group`` names a gremium, that is a UUID as text."""
        try:
            UUID(eligible_group)
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def _may_cast(principal: Principal, eligible_group: str) -> bool:
        """Tell whether the principal may cast an OWN ballot in this vote.

        Only the namespaced key ``vote:<gremium_id>`` decides. `resolve_principal`
        writes it for an active membership whose gremium role carries ``vote.cast``,
        and for nothing else, so the key proves the right. A matching OIDC group claim
        cannot satisfy it. `MeetingRules.vote_eligible_count` builds the quorum
        denominator from exactly that roster, so both sides use the same rule.

        A free group key (not a UUID) is an old row. No global permission grants a
        vote right, so such a vote admits nobody.
        """
        if not VoteAccessOps._is_gremium_group(eligible_group):
            return False
        return principal.in_group(vote_group_key(eligible_group))

    def can_cast_own(self, vote: Vote, principal: Principal) -> bool:
        """Tell whether the principal may cast an own ballot (the ``canCast`` flag).

        The rule is the roster side of ``cast``: a human session (no OAuth token) and
        ``vote.cast`` in the gremium of the vote. A delegated ballot has its own check.
        """
        return principal.scope_permissions is None and self._may_cast(
            principal, vote.eligible_group
        )

    async def _all_cast(self, vote: Vote, represented: tuple[Represented, ...]) -> bool:
        """Tell whether every represented member has a ballot in ``vote``.

        True without a represented member: nothing is left to cast then.
        """
        subs = [r.sub for r in represented]
        if not subs:
            return True
        cast_count = await self.session.scalar(
            select(func.count())
            .select_from(VotedMarker)
            .where(VotedMarker.vote_id == vote.id, VotedMarker.voter_sub.in_(subs))
        )
        return int(cast_count or 0) >= len(set(subs))

    async def assert_can_read(self, vote: Vote, principal: Principal) -> None:
        """Guard read access to a vote (broken object level authorization).

        A meeting-bound vote follows the meeting visibility rules of
        ``MeetingRules.assert_can_read``: member, participant, or delegation
        recipient. A vote without a meeting (application vote) is readable with
        ``application.read`` or ``application.read_all`` (the admin role holds both),
        for an eligible voter of the vote, and for a holder of the gremium permission
        ``vote.manage`` or ``session.manage`` in the gremium of the vote. Without this
        check any logged-in user could read the tally of another gremium through
        ``GET /api/votes/{id}``, including closed SECRET votes.

        The admin role reaches this through `Principal.has`, not through a
        `principal.roles` read: `has` is where the OAuth scope cap applies.

        A poll and an Umlaufverfahren of a Gremium (``kind = poll`` or ``circular``, no
        meeting) are no application votes, so the global application rights do not
        reach them: only an eligible voter, a
        manager in its Gremium and the admin role (``admin_bypass``) read it.

        Raises:
            ForbiddenError: The principal cannot view this vote.
        """
        if vote.meeting_id is not None:
            from app.modules.meetings.rules import MeetingRules

            await MeetingRules(self.session).assert_can_read(vote.meeting_id, principal)
            return
        if poll_mod.is_poll(vote) or circular_mod.is_circular(vote):
            from app.modules.auth.policy import admin_bypass

            if admin_bypass(principal, "application.read"):
                return
        elif principal.has("application.read") or principal.has("application.read_all"):
            return
        if self._may_cast(principal, vote.eligible_group):
            return
        gremium_id = await self._vote_gremium_id(
            meeting_id=None, eligible_group=vote.eligible_group
        )
        if gremium_id is not None and await holds_gremium_vote_role(
            self.session, gremium_id, principal
        ):
            return
        raise ForbiddenError("not allowed to view this vote")

    async def get_scoped(self, vote_id: UUID, principal: Principal) -> VoteOut:
        """Like ``get`` but fail-closed scoped to the vote's read audience.

        The result carries the ``canManage`` and ``canCast`` flags of the principal,
        the own ballot (``myBallot``) and ``representedCast``.
        """
        vote = await self._get_vote(vote_id)
        await self.assert_can_read(vote, principal)
        out = await self.get(vote_id)
        return out.model_copy(
            update={
                "can_manage": await self.can_manage(vote, principal),
                "can_cast": self.can_cast_own(vote, principal),
                "my_ballot": await self.my_ballot(vote, principal.sub),
                "represented_cast": await self.represented_cast(vote, principal.sub),
            }
        )

    async def my_ballot(self, vote: Vote, voter_sub: str) -> MyBallot:
        """Return the ballot that ``voter_sub`` cast in this vote.

        The method reads only the ``voted_marker``: the choice has no link to the
        voter, so ``choice`` stays None.
        """
        marker = await self.session.scalar(
            select(VotedMarker.id).where(
                VotedMarker.vote_id == vote.id, VotedMarker.voter_sub == voter_sub
            )
        )
        return MyBallot(cast=marker is not None)

    async def represented_cast(self, vote: Vote, sub: str) -> bool:
        """Tell whether ``sub`` represents members and all their ballots are in.

        A represented ballot runs under the ``sub`` of the delegator
        (``voting_delegation_check``). The method returns False without a represented
        member that ``vote`` takes a ballot for.
        """
        _, incoming = await voting_delegation_check(
            self.session, sub, vote.meeting_id, vote.eligible_group, datetime.now(UTC)
        )
        represented = await self._represented_in(vote, incoming)
        return bool(represented) and await self._all_cast(vote, represented)

    async def _vote_gremium_id(
        self, *, meeting_id: UUID | None, eligible_group: str
    ) -> UUID | None:
        """Resolve the gremium of a vote.

        A meeting-bound vote inherits the gremium of the meeting. A vote without a
        meeting (application vote) carries the gremium in ``eligible_group`` as the
        gremium UUID in text form. If ``eligible_group`` is a free group key and not a
        UUID (an old row), no gremium resolves and the method returns ``None``. Only
        the admin role then grants access.
        """
        if meeting_id is not None:
            from app.modules.meetings.models import Meeting

            gid = await self.session.scalar(
                select(Meeting.gremium_id).where(Meeting.id == meeting_id)
            )
            if gid is not None:
                return gid
        try:
            return UUID(eligible_group)
        except (ValueError, TypeError):
            return None

    async def _meeting_grants_vote_management(self, meeting_id: UUID, principal: Principal) -> bool:
        """Ask the meeting rule that the client sees as ``canManageVotes``.

        The meeting payload publishes ``canManageVotes``, and the client renders the
        open, close and delete buttons from it. This gate must therefore admit exactly
        the people that flag names, or the UI offers an action that the API refuses.
        ``MeetingRules.can_manage_votes`` is the single source of that rule: the
        session manager, the protokollant, or the gremium rule
        (``manages_votes_in_gremium``).

        The protokollant is an active member of the gremium of the meeting, which
        ``_resolve_protokollant`` enforces, so this reaches no other gremium. The same
        people already create, open and delete the votes of the meeting through
        ``/meetings/{id}/votes``, so the close and the cancel add no right that the
        delete does not already carry.
        """
        from app.modules.meetings.models import Meeting
        from app.modules.meetings.rules import MeetingRules

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            return False
        return await MeetingRules(self.session).can_manage_votes(meeting, principal)

    async def can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> bool:
        """Tell whether the principal may manage a vote of this group and meeting.

        The rule is fail-closed and gremium-scoped, symmetric to ``assert_can_read``.
        It covers create, open, close, cancel and delete. The checks run in this
        order:

        1. For a meeting-bound vote, the meeting rule
           (``PermissionOps.can_manage_votes``). It keeps the enforced right equal to
           the advertised ``canManageVotes`` flag, and it holds the gremium rule.
        2. The gremium rule (``manages_votes_in_gremium``) in the gremium of the vote:
           the admin role or a gremium role with ``vote.manage`` or
           ``session.manage``. This covers the application vote that no meeting holds,
           and a vote whose meeting is gone.

        A vote with a free group key resolves no gremium, so only the admin role
        passes.
        """
        if meeting_id is not None and await self._meeting_grants_vote_management(
            meeting_id, principal
        ):
            return True
        gremium_id = await self._vote_gremium_id(
            meeting_id=meeting_id, eligible_group=eligible_group
        )
        if gremium_id is None:
            from app.modules.auth.policy import admin_bypass

            return admin_bypass(principal, "vote.manage")
        return await manages_votes_in_gremium(self.session, gremium_id, principal)

    async def assert_can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> None:
        """Guard the write and lifecycle access to a vote (``can_manage_group``).

        Raises:
            ForbiddenError: The principal cannot manage this vote.
        """
        if not await self.can_manage_group(eligible_group, meeting_id, principal):
            raise ForbiddenError("not allowed to manage this vote")

    async def can_manage(self, vote: Vote, principal: Principal) -> bool:
        """Like ``can_manage_group`` but for an already-loaded vote.

        A poll and an Umlaufverfahren of a Gremium (no meeting) take the right that creates them
        (``PollService.can_create``: ``vote.manage`` or the admin role), so
        ``session.manage`` alone cannot edit, open, close, cancel or delete a poll
        that it cannot create.
        """
        if (poll_mod.is_poll(vote) or circular_mod.is_circular(vote)) and vote.meeting_id is None:
            gremium_id = await self._vote_gremium_id(
                meeting_id=None, eligible_group=vote.eligible_group
            )
            if gremium_id is None:
                from app.modules.auth.policy import admin_bypass

                return admin_bypass(principal, "vote.manage")
            return await poll_mod.PollService(cast("VotingService", self)).can_create(
                gremium_id, principal
            )
        return await self.can_manage_group(vote.eligible_group, vote.meeting_id, principal)

    async def assert_can_manage(self, vote: Vote, principal: Principal) -> None:
        """Like ``assert_can_manage_group`` but for an already-loaded vote (``can_manage``).

        Raises:
            ForbiddenError: The principal cannot manage this vote.
        """
        if not await self.can_manage(vote, principal):
            raise ForbiddenError("not allowed to manage this vote")

    async def meeting_id_of(self, vote_id: UUID) -> UUID | None:
        """Return the meeting of the vote, or None for a vote without a meeting."""
        return await self.session.scalar(select(Vote.meeting_id).where(Vote.id == vote_id))

    async def assert_can_run_vote(self, vote_id: UUID, principal: Principal) -> None:
        """Guard the open and the close of a vote.

        The manage right (``assert_can_manage_vote``) comes first. A vote that a
        meeting holds then needs the protokollant of that meeting
        (``MeetingRules.assert_can_run_votes``): the open and the close follow the
        minutes. A vote without a meeting keeps the manage right only.

        Raises:
            NotFoundError: No vote has this id.
            ForbiddenError: The principal cannot manage this vote, or the vote belongs
                to a meeting and the principal is not its protokollant.
        """
        await self.assert_can_manage_vote(vote_id, principal)
        meeting_id = await self.meeting_id_of(vote_id)
        if meeting_id is None:
            return
        from app.modules.meetings.rules import MeetingRules

        await MeetingRules(self.session).assert_can_run_votes(meeting_id, principal)

    async def assert_can_manage_vote(self, vote_id: UUID, principal: Principal) -> None:
        """Load the vote and run ``assert_can_manage`` on it.

        The ``/votes/{id}/{open,close,cancel}`` router calls this before the lifecycle
        call. Open, close and cancel are therefore fail-closed and gremium-scoped like
        ``get_scoped``. The internal live-vote and cron path calls the lifecycle
        methods directly with its own gate. It bypasses this check on purpose.

        Raises:
            NotFoundError: No vote has this id.
            ForbiddenError: The principal cannot manage this vote.
        """
        vote = await self._get_vote(vote_id)
        await self.assert_can_manage(vote, principal)

    async def list_visible(
        self,
        principal: Principal,
        *,
        statuses: Sequence[VoteStatus] | None = None,
        gremium_id: UUID | None = None,
        q: str | None = None,
        kind: VoteKind | None = None,
        cancelled_reason: CancelReason | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> Page[VoteListItem]:
        """Return one page of the votes that the principal can read (``GET /votes``).

        The read rule is the rule of ``assert_can_read``, applied in SQL. See
        ``app.modules.voting.listing``.
        """
        from app.modules.voting.listing import list_votes

        return await list_votes(
            self.session,
            principal,
            statuses=statuses,
            gremium_id=gremium_id,
            q=q,
            kind=kind,
            cancelled_reason=cancelled_reason,
            limit=limit,
            offset=offset,
        )

    async def get(self, vote_id: UUID) -> VoteOut:
        """Return the vote state and the aggregated tally.

        A secret vote exposes only the counts and never the voters. This method has no
        scope gate. It is the internal reuse path, for example the tally broadcast
        after ``cast``. The public read endpoint uses ``get_scoped``.

        The stored result is text, cast back to ``VoteResult`` because ``tally.result``
        only writes its Literal values.
        """
        vote = await self._get_vote(vote_id)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        tally_out = await self._tally_out(vote, config, counts, vote.eligible_count or 0)
        return self._to_out(vote, config, _with_stored_result(tally_out, vote))

    async def vote_gremium_mismatch(self, vote: Vote) -> bool:
        """Tell whether the Gremium of ``vote`` does not decide its application now.

        The check applies only while the application sits in a ``vote`` state. The
        Gremium of the vote (the meeting Gremium, else ``eligible_group``) must be the
        snapshot ``application.vote_gremium_id``. A missing snapshot counts as a
        mismatch (fail closed). A vote without an application, and an application
        outside a vote state, give False: nothing fires a branch there.
        """
        if vote.application_id is None:
            return False
        from app.modules.flow.models import State

        row = (
            await self.session.execute(
                select(Application.vote_gremium_id, State.kind)
                .join(State, State.id == Application.current_state_id)
                .where(Application.id == vote.application_id)
            )
        ).first()
        if row is None or row[1] != "vote":
            return False
        actual = await self._vote_gremium_id(
            meeting_id=vote.meeting_id, eligible_group=vote.eligible_group
        )
        return row[0] is None or actual != row[0]
