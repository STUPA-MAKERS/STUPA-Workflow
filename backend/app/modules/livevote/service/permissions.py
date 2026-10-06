"""RBAC checks, visibility scope, and the permission-flag serializer.

The server scopes management, write access, vote management and finalization per
gremium role (`session.manage`, `protocol.write`, `vote.manage`,
`protocol.finalize`). No global permission grants them. The admin role bypasses the
gremium check. The OAuth scope cap applies to all of these rights, the admin bypass
included. The `meeting.view_all` permission is global, read-only, and purely additive.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.admin.gremium_roles import (
    admin_bypass,
    gremium_ids_for,
    gremium_ids_with_permission,
    gremium_member_ids,
)
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.delegations.pool import substitute_gremien_for_sub
from app.modules.livevote.keepers import keeper_summaries
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingOut, MeetingVoteOut
from app.modules.livevote.service.service_base import MeetingServiceBase
from app.shared.errors import ForbiddenError


class PermissionOps(MeetingServiceBase):
    """Per-principal permission checks and visibility scoping."""

    async def can_manage(self, gremium_id: UUID, principal: Principal) -> bool:
        """Check for meeting management: gremium `session.manage` or the admin role.

        The scope cap applies: a token without `session.manage` in its scope cannot
        manage, not even an admin token.
        """
        if admin_bypass(principal, "session.manage"):
            return True
        return gremium_id in await gremium_ids_for(self.session, principal, "session.manage")

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
        return meeting.gremium_id in await gremium_ids_for(
            self.session, principal, "protocol.write"
        )

    async def can_write_meeting(self, meeting_id: UUID, principal: Principal) -> bool:
        """Load the meeting and run `can_write` (the meeting lead check).

        Raises:
            NotFoundError: The meeting does not exist.
        """
        return await self.can_write(await self._get(meeting_id), principal)

    async def can_manage_votes(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who opens and closes votes: manager, protokollant, or `vote.manage`.

        The admin role bypasses the gremium check. That keeps this rule equal to
        the `admin_bypass(principal, "vote.manage")` gate of
        `VotingService.can_manage_group` and to the batched flags of the meeting
        list. The protokollant path, the gremium role, and the admin bypass are
        scope-capped: through them, a token without `vote.manage` in its scope cannot
        manage votes.

        The manager path needs only `session.manage`. The meeting lead includes
        vote management and the agenda-item change, so a `meetings:write` token
        of a manager can manage votes without `votes:write`.
        """
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if admin_bypass(principal, "vote.manage"):
            return True
        if principal.scope_allows("vote.manage") and await self._is_protokollant(
            meeting, principal
        ):
            return True
        return meeting.gremium_id in await gremium_ids_for(
            self.session, principal, "vote.manage"
        )

    async def can_finalize(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who finalizes and sends the protocol of a meeting.

        The principal needs the write access (`can_write`) AND the gremium permission
        `protocol.finalize` in the gremium of the meeting. The admin role bypasses the
        gremium check. The scope cap applies to both parts.
        """
        if not await self.can_write(meeting, principal):
            return False
        if admin_bypass(principal, "protocol.finalize"):
            return True
        return meeting.gremium_id in await gremium_ids_for(
            self.session, principal, "protocol.finalize"
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
        """
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
        stmt = select(MeetingDelegation.meeting_id).where(
            MeetingDelegation.delegate_principal_id == pid_subq
        )
        if voting_only:
            stmt = stmt.where(MeetingDelegation.delegate_voting.is_(True))
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

    async def meeting_read_scope(
        self, principal: Principal
    ) -> tuple[set[UUID] | None, set[UUID]]:
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

        Returns:
            The visible gremium ids, or `None` for all gremien.
        """
        # Both checks apply the OAuth scope cap. `Principal.has` grants the admin role
        # every in-scope right. Reading `principal.roles` here would return `None` —
        # every gremium — for a token scoped to far less.
        if principal.has("meeting.view_all") or admin_bypass(principal, "session.manage"):
            return None
        member = await gremium_member_ids(self.session, principal.sub)
        pool = await self._substitute_pool_gremium_ids(principal.sub)
        return member | pool

    async def _substitute_pool_gremium_ids(self, sub: str) -> set[UUID]:
        """Return the gremien whose substitute pool contains `sub`.

        The pool covers `delegation_substitute` and the faculty groups (Z5).
        """
        return await substitute_gremien_for_sub(self.session, sub)

    async def _emit(
        self,
        meeting: Meeting,
        principal: Principal | None,
        *,
        protocol_id: UUID | None = None,
        votes: list[MeetingVoteOut] | None = None,
    ) -> MeetingOut:
        """Build the `MeetingOut` with the permission flags of the principal."""
        name = await self._name_for(self.session, meeting.protokollant_id)
        gremium_name = await self._gremium_name_for(meeting.gremium_id)
        agenda = (await self._agenda_summaries([meeting]))[meeting.id]
        keepers = (await keeper_summaries(self.session, [meeting.id]))[meeting.id]
        guests = (await self._guest_counts([meeting.id])).get(meeting.id, (0, 0))
        if principal is None:
            return self._to_out(
                meeting,
                protocol_id,
                protokollant_name=name,
                gremium_name=gremium_name,
                votes=votes,
                agenda=agenda,
                keepers=keepers,
                guests=guests,
            )
        return self._to_out(
            meeting,
            protocol_id,
            can_manage=await self.can_manage(meeting.gremium_id, principal),
            can_write=await self.can_write(meeting, principal),
            can_manage_votes=await self.can_manage_votes(meeting, principal),
            can_vote=await self.can_vote(meeting, principal),
            can_finalize=await self.can_finalize(meeting, principal),
            is_protokollant=await self._is_protokollant(meeting, principal),
            protokollant_name=name,
            gremium_name=gremium_name,
            votes=votes,
            agenda=agenda,
            keepers=keepers,
            guests=guests,
        )
