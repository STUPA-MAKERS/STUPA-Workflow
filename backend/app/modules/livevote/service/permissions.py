"""RBAC checks, visibility scope, and the permission-flag serializer.

The server scopes management, write access, and vote management per gremium role.
The `meeting.view_all` permission is global, read-only, and purely additive.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.admin.gremium_roles import (
    gremium_ids_with_permission,
    gremium_member_ids,
)
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingOut, MeetingVoteOut
from app.modules.livevote.service.service_base import MeetingServiceBase
from app.shared.errors import ForbiddenError


class PermissionOps(MeetingServiceBase):
    """Per-principal permission checks and visibility scoping."""

    async def can_manage(self, gremium_id: UUID, principal: Principal) -> bool:
        """Check for meeting management: global `meeting.manage` or gremium `session.manage`."""
        if principal.has("meeting.manage"):  # the admin role also holds this permission
            return True
        return gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "session.manage"
        )

    async def _is_protokollant(self, meeting: Meeting, principal: Principal) -> bool:
        if meeting.protokollant_id is None:
            return False
        return meeting.protokollant_id == await self._principal_id(principal.sub)

    async def can_write(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who runs the protocol, the agenda items, and the meeting status.

        The manager, the assigned protokollant, and a gremium role with
        `protocol.write` all pass this check.
        """
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await self._is_protokollant(meeting, principal):
            return True
        return meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "protocol.write"
        )

    async def can_manage_votes(self, meeting: Meeting, principal: Principal) -> bool:
        """Check who opens and closes votes: manager, protokollant, or `vote.manage`."""
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await self._is_protokollant(meeting, principal):
            return True
        return meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "vote.manage"
        )

    async def can_vote(self, meeting: Meeting, principal: Principal) -> bool:
        """Check if the principal can vote in this meeting.

        An admin passes. A gremium role with `vote.cast` passes. A voting delegation
        of this meeting that names the principal also passes. The last case covers an
        external substitute.
        """
        if "admin" in principal.roles:
            return True
        if meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "vote.cast"
        ):
            return True
        return meeting.id in await self._delegated_meeting_ids(principal.sub, voting_only=True)

    async def is_member(self, gremium_id: UUID, principal: Principal) -> bool:
        """Check for current membership in the gremium with any role.

        A member can follow the meeting live.
        """
        if "admin" in principal.roles:
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

        An admin, a holder of `meeting.manage`, a member or pool substitute of the
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

    async def _visible_gremium_ids(self, principal: Principal) -> set[UUID] | None:
        """Return the gremien whose meetings the principal can see.

        An admin and a holder of `meeting.manage` or `meeting.view_all` see
        everything. Every other principal sees the gremien of membership with any
        role plus the substitute-pool gremien. Pool standing grants timeline
        visibility only. The live channel needs a concrete delegation. See
        `is_participant`. The `meeting.view_all` permission is global, read-only, and
        purely additive. The server gates management, write access, and voting
        separately.

        Returns:
            The visible gremium ids, or `None` for all gremien.
        """
        if (
            "admin" in principal.roles
            or principal.has("meeting.manage")
            or principal.has("meeting.view_all")
        ):
            return None
        member = await gremium_member_ids(self.session, principal.sub)
        pool = await self._substitute_pool_gremium_ids(principal.sub)
        return member | pool

    async def _substitute_pool_gremium_ids(self, sub: str) -> set[UUID]:
        """Return the gremien whose substitute pool contains `sub`."""
        pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
        stmt = select(DelegationSubstitute.gremium_id).where(
            DelegationSubstitute.substitute_principal_id == pid_subq
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def _emit(
        self,
        meeting: Meeting,
        principal: Principal | None,
        *,
        protocol_id: UUID | None = None,
        votes: list[MeetingVoteOut] | None = None,
    ) -> MeetingOut:
        """Build the `MeetingOut` with the four permission flags of the principal."""
        name = await self._name_for(self.session, meeting.protokollant_id)
        gremium_name = await self._gremium_name_for(meeting.gremium_id)
        if principal is None:
            return self._to_out(
                meeting,
                protocol_id,
                protokollant_name=name,
                gremium_name=gremium_name,
                votes=votes,
            )
        return self._to_out(
            meeting,
            protocol_id,
            can_manage=await self.can_manage(meeting.gremium_id, principal),
            can_write=await self.can_write(meeting, principal),
            can_manage_votes=await self.can_manage_votes(meeting, principal),
            can_vote=await self.can_vote(meeting, principal),
            is_protokollant=await self._is_protokollant(meeting, principal),
            protokollant_name=name,
            gremium_name=gremium_name,
            votes=votes,
        )
