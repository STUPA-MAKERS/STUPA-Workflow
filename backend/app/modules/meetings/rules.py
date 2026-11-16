"""The rules of a meeting: who reads it, who writes it and who runs its votes.

The server scopes management, write access, vote management and finalization per
gremium role (`session.manage`, `protocol.write`, `vote.manage`,
`protocol.finalize`). No global permission grants them. The admin role bypasses the
gremium check. The OAuth scope cap applies to all of these rights, the admin bypass
included. The `meeting.view_all` permission is global, read-only, and purely additive.

`MeetingRules` is the class for a caller that needs only the rules (`voting`, `flow`).
`livevote.service.MeetingService` takes the same methods through `MeetingRuleOps`
(§S/backend/python/000652).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.policy import admin_bypass, has_gremium_permission
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.gremium_roles import gremium_ids_with_permission, gremium_member_ids
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.gremien.pool import substitute_gremien_for_sub
from app.modules.meetings.models import Meeting
from app.modules.site_config.features import Feature, feature_on
from app.modules.voting.service import manages_votes_in_gremium
from app.shared.errors import ForbiddenError, NotFoundError


class MeetingReads:
    """The reads of one meeting that the rules and the meeting service share."""

    session: AsyncSession

    async def _principal_id(self, sub: str) -> UUID | None:
        """Return the `principal.id` for an OIDC `sub`, used for the protokollant check."""
        return (
            await self.session.execute(select(PrincipalRow.id).where(PrincipalRow.sub == sub))
        ).scalar_one_or_none()

    async def _get(self, meeting_id: UUID, *, for_update: bool = False) -> Meeting:
        """Load a meeting by id.

        ``for_update`` locks the meeting row until the commit and reads the current
        values again. A status change, an agenda change and a vote open all take this
        lock first, so they run one after the other.

        Raises:
            NotFoundError: No meeting has this id.
        """
        query = select(Meeting).where(Meeting.id == meeting_id)
        stmt = (
            query.with_for_update().execution_options(populate_existing=True)
            if for_update
            else query
        )
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting


class MeetingRuleOps(MeetingReads):
    """Per-principal permission checks and visibility scoping."""

    async def can_manage(self, gremium_id: UUID, principal: Principal) -> bool:
        """Check for meeting management: gremium `session.manage` or the admin role.

        The scope cap applies: a token without `session.manage` in its scope cannot
        manage, not even an admin token.
        """
        return await has_gremium_permission(self.session, principal, "session.manage", gremium_id)

    async def meeting_gremium_id(self, meeting_id: UUID) -> UUID:
        """Return the gremium of a meeting.

        Raises:
            NotFoundError: The meeting does not exist.
        """
        return (await self._get(meeting_id)).gremium_id

    async def _is_protokollant(self, meeting: Meeting, principal: Principal) -> bool:
        if meeting.protokollant_id is None:
            return False
        return meeting.protokollant_id == await self._principal_id(principal.sub)

    async def can_write(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who runs the protocol, the agenda items, and the meeting status.

        The manager, the assigned protokollant, and a gremium role with
        `protocol.write` all pass this check. The admin role bypasses the gremium
        check. The scope cap applies to every path: a token without
        `protocol.write` in its scope cannot write through the protokollant path,
        the gremium role, or the admin bypass.
        """
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if admin_bypass(principal, "protocol.write"):
            return True
        if principal.scope_allows("protocol.write") and await self._is_protokollant(
            meeting, principal
        ):
            return True
        return await has_gremium_permission(
            self.session, principal, "protocol.write", meeting.gremium_id
        )

    async def can_write_meeting(self, meeting_id: UUID, principal: Principal) -> bool:
        """Load the meeting and run `can_write` (the meeting lead check).

        Raises:
            NotFoundError: The meeting does not exist.
        """
        return await self.can_write(await self._get(meeting_id), principal)

    async def can_set_current_item(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who sets the current agenda item: the protokollant of the meeting only.

        The session lead, a gremium role and the admin role do not pass, because the
        current item moves the beamer and every follower. The scope cap applies: a
        token without `protocol.write` in its scope cannot set it.
        """
        return principal.scope_allows("protocol.write") and await self._is_protokollant(
            meeting, principal
        )

    async def can_mark_done(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who sets the done mark of an agenda item: the writer of its text.

        This is the gate of the agenda-item text (`set_agenda_body`): `can_write`, and
        in a live meeting with a protokollant only the protokollant. The protocol state
        is a separate check of the agenda service.
        """
        if not await self.can_write(meeting, principal):
            return False
        if meeting.status == "live" and meeting.protokollant_id is not None:
            return await self._is_protokollant(meeting, principal)
        return True

    async def can_run_votes(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who opens and closes the votes of a meeting: the protokollant only.

        The session lead, a gremium role with `vote.manage` and the admin role still
        prepare, cancel and delete votes (`can_manage_votes`), but the open and the
        close follow the minutes. The scope cap applies: a token without `vote.manage`
        in its scope cannot open or close.
        """
        return principal.scope_allows("vote.manage") and await self._is_protokollant(
            meeting, principal
        )

    async def assert_can_run_votes(self, meeting_id: UUID, principal: Principal) -> None:
        """Load the meeting and refuse anybody but its protokollant (`can_run_votes`).

        Raises:
            NotFoundError: The meeting does not exist.
            ForbiddenError: The principal is not the protokollant of the meeting.
        """
        if not await self.can_run_votes(await self._get(meeting_id), principal):
            raise ForbiddenError("only the protokollant may open or close a vote")

    async def can_manage_votes(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who manages the votes of a meeting: manager, gremium rule, protokollant.

        The meeting rule adds the session lead (`can_manage`) and the protokollant to
        the gremium rule of vote management (`voting.service.manages_votes_in_gremium`:
        the admin role or a gremium role with `vote.manage` or `session.manage`).
        `VotingService.can_manage_group` asks this method for a meeting-bound vote, so
        the enforced right equals the advertised `canManageVotes` flag. The batched
        flags of the meeting list (`ListingOps`) compute the same union. The
        protokollant path, the gremium role, and the admin bypass are scope-capped:
        through them, a token without `vote.manage` in its scope cannot manage votes.

        The manager path needs only `session.manage`. The meeting lead includes
        vote management and the agenda-item change, so a `meetings:write` token
        of a manager can manage votes without `votes:write`. Nobody manages a vote while
        `Abstimmungen` is off (§F/administration/admin/000757).
        """
        if not await feature_on(self.session, Feature.VOTING):
            return False
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await manages_votes_in_gremium(self.session, meeting.gremium_id, principal):
            return True
        return principal.scope_allows("vote.manage") and await self._is_protokollant(
            meeting, principal
        )

    async def can_finalize(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who finalizes and sends the protocol of a meeting.

        The principal needs the write access (`can_write`) AND the gremium permission
        `protocol.finalize` in the gremium of the meeting. The admin role bypasses the
        gremium check. The scope cap applies to both parts.
        """
        if not await self.can_write(meeting, principal):
            return False
        return await has_gremium_permission(
            self.session, principal, "protocol.finalize", meeting.gremium_id
        )

    async def can_vote(self, meeting: Meeting, principal: Principal) -> bool:
        """Check if the principal can vote in this meeting.

        A gremium role with `vote.cast` passes. A voting delegation of this meeting
        that names the principal also passes. The last case covers an external
        substitute.

        The flag mirrors the cast gate of `VotingService`, which admits the gremium
        roster of the vote and nobody else. The admin role is therefore not enough on
        its own: an admin without a membership in this gremium would see a ballot UI
        that the API then refuses with 403. The quorum counts
        that admin as little as the gate admits them.

        Voting also stays human. `vote.cast` sits in FORBIDDEN_PERMISSIONS, and the
        cast gate refuses every scoped OAuth token.

        Nobody votes while `Abstimmungen` is off (§F/administration/admin/000757).
        """
        if not await feature_on(self.session, Feature.VOTING):
            return False
        if meeting.gremium_id in await self._vote_cast_gremium_ids(principal):
            return True
        return meeting.id in await self._delegated_meeting_ids(principal.sub, voting_only=True)

    async def _vote_cast_gremium_ids(self, principal: Principal) -> set[UUID]:
        """Return the gremien whose roster admits this principal to a ballot.

        This is the roster side of the cast gate, and the same set that
        `vote_eligible_count` counts for the quorum. A scoped OAuth token gets the
        empty set: `vote.cast` sits in FORBIDDEN_PERMISSIONS, and voting stays human.
        """
        if principal.scope_permissions is not None:
            return set()
        return await gremium_ids_with_permission(self.session, principal.sub, "vote.cast")

    async def is_member(self, gremium_id: UUID, principal: Principal) -> bool:
        """Check for current membership in the gremium with any role.

        A member can follow the meeting live, and so can the holder of the global
        `meeting.view_all` read right, which the admin role carries. That right goes
        through `Principal.has`, so the OAuth scope cap applies: a raw `principal.roles`
        read would give a narrowly scoped token the cross-gremium roster, which carries
        names and email addresses.
        """
        if principal.has("meeting.view_all"):
            return True
        return gremium_id in await gremium_member_ids(self.session, principal.sub)

    async def is_participant(
        self, meeting_id: UUID, gremium_id: UUID, principal: Principal
    ) -> bool:
        """Check if the principal is a member or a delegation recipient of this meeting.

        Both can follow the meeting live. An external substitute is not a gremium
        member but still needs the live channel for the delegation. The
        `meeting.view_all` permission opens the live read channel across all gremien.
        It stays read-only. The `can_vote` check and `vote.cast` still gate voting.
        """
        if await self.is_member(gremium_id, principal):
            return True
        if principal.has("meeting.view_all"):
            return True
        return meeting_id in await self._delegated_meeting_ids(principal.sub)

    async def _delegated_meeting_ids(self, sub: str, *, voting_only: bool = False) -> set[UUID]:
        """Return the meetings in which `sub` receives a delegation.

        With `voting_only`, the result holds only the delegations that transfer the
        vote.
        """
        pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
        query = select(MeetingDelegation.meeting_id).where(
            MeetingDelegation.delegate_principal_id == pid_subq
        )
        stmt = query.where(MeetingDelegation.delegate_voting.is_(True)) if voting_only else query
        return set((await self.session.execute(stmt)).scalars().all())

    async def assert_can_read(self, meeting_id: UUID, principal: Principal) -> None:
        """Guard read access to the meeting detail, the roster, and the agenda.

        An admin, a holder of `meeting.view_all`, a member or pool substitute of the
        gremium, and a delegation recipient of this meeting can read. This matches
        the visibility of the timeline. The guard blocks cross-tenant reads, because
        the roster carries names and email addresses.

        Raises:
            NotFoundError: The meeting does not exist.
            ForbiddenError: The principal cannot view this meeting.
        """
        meeting = await self._get(meeting_id)
        visible = await self._visible_gremium_ids(principal)
        if visible is None or meeting.gremium_id in visible:
            return
        if meeting_id in await self._delegated_meeting_ids(principal.sub):
            return
        raise ForbiddenError("not allowed to view this meeting")

    async def meeting_read_scope(self, principal: Principal) -> tuple[set[UUID] | None, set[UUID]]:
        """Return the read scope of `assert_can_read` as two id sets.

        The first set holds the gremien whose meetings the principal can read. `None`
        means all gremien. The second set holds the meetings in which the principal
        receives a delegation. It is empty when the first set is `None`, because the
        principal then reads every meeting. The vote list (`GET /votes`) filters the
        meeting votes with this scope, so the list and the single read agree.
        """
        visible = await self._visible_gremium_ids(principal)
        if visible is None:
            return None, set()
        return visible, await self._delegated_meeting_ids(principal.sub)

    async def _visible_gremium_ids(self, principal: Principal) -> set[UUID] | None:
        """Return the gremien whose meetings the principal can see.

        An admin and a holder of `meeting.view_all` see everything. The admin path
        needs `session.manage` or `meeting.view_all` in the token scope. Every other
        principal sees the gremien of membership with any role plus the
        substitute-pool gremien. Pool standing grants timeline visibility only. The
        live channel needs a concrete delegation. See `is_participant`. The
        `meeting.view_all` permission is global, read-only, and purely additive. The
        server gates management, write access, and voting separately.

        Both checks apply the OAuth scope cap. `Principal.has` grants the admin role every
        in-scope right. A read of `principal.roles` here would return `None`, that is every
        gremium, for a token scoped to far less.

        Returns:
            The visible gremium ids, or `None` for all gremien.
        """
        if principal.has("meeting.view_all") or admin_bypass(principal, "session.manage"):
            return None
        member = await gremium_member_ids(self.session, principal.sub)
        pool = await self._substitute_pool_gremium_ids(principal.sub)
        return member | pool

    async def _substitute_pool_gremium_ids(self, sub: str) -> set[UUID]:
        """Return the gremien whose substitute pool contains `sub`."""
        return await substitute_gremien_for_sub(self.session, sub)

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        """Return the roster size for the quorum: active members with a `vote.cast` role."""
        datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(GremiumMembership.principal_id, GremiumRole.permissions)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.gremium_id == gremium_id,
                )
            )
        ).all()
        return len({pid for pid, perms in rows if "vote.cast" in (perms or [])})


class MeetingRules(MeetingRuleOps):
    """The meeting rules bound to one `AsyncSession`."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the rules to the session of the request."""
        self.session = session
