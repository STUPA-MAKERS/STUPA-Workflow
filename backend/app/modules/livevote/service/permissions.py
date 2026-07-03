"""RBAC checks, visibility scope, and the permission-flag serializer.

Server-side scope model: managing/writing/vote management stay gated per gremium
role; ``meeting.view_all`` is a purely additive, read-only global permission.
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
        """Manage the meeting: global ``meeting.manage`` OR gremium ``session.manage``."""
        if principal.has("meeting.manage"):  # also covers admin
            return True
        return gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "session.manage"
        )

    async def _is_protokollant(self, meeting: Meeting, principal: Principal) -> bool:
        if meeting.protokollant_id is None:
            return False
        return meeting.protokollant_id == await self._principal_id(principal.sub)

    async def can_write(self, meeting: Meeting, principal: Principal) -> bool:
        """Run protocol/TOPs/status: manager, assigned protokollant OR a role with
        ``protocol.write``."""
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await self._is_protokollant(meeting, principal):
            return True
        return meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "protocol.write"
        )

    async def can_manage_votes(self, meeting: Meeting, principal: Principal) -> bool:
        """Open/close votes: manager, protokollant OR ``vote.manage``."""
        if await self.can_manage(meeting.gremium_id, principal):
            return True
        if await self._is_protokollant(meeting, principal):
            return True
        return meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "vote.manage"
        )

    async def can_vote(self, meeting: Meeting, principal: Principal) -> bool:
        """Eligible to vote: admin, a gremium role with ``vote.cast`` OR a voting
        delegation of this meeting addressed to the principal (external substitute)."""
        if "admin" in principal.roles:
            return True
        if meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "vote.cast"
        ):
            return True
        return meeting.id in await self._delegated_meeting_ids(principal.sub, voting_only=True)

    async def is_member(self, gremium_id: UUID, principal: Principal) -> bool:
        """Current member of the gremium (any role) — may follow live."""
        if "admin" in principal.roles:
            return True
        return gremium_id in await gremium_member_ids(self.session, principal.sub)

    async def is_participant(
        self, meeting_id: UUID, gremium_id: UUID, principal: Principal
    ) -> bool:
        """Member OR delegation recipient of this meeting — may follow live.

        External substitutes are not gremium members but need the live channel for
        their delegation. ``meeting.view_all`` opens the live read channel across
        gremien (read-only — VOTING stays gated via ``can_vote``/``vote.cast``).
        """
        if await self.is_member(gremium_id, principal):
            return True
        if principal.has("meeting.view_all"):
            return True
        return meeting_id in await self._delegated_meeting_ids(principal.sub)

    async def _delegated_meeting_ids(self, sub: str, *, voting_only: bool = False) -> set[UUID]:
        """Meetings for which ``sub`` RECEIVES a (voting) delegation."""
        pid_subq = select(PrincipalRow.id).where(PrincipalRow.sub == sub).scalar_subquery()
        stmt = select(MeetingDelegation.meeting_id).where(
            MeetingDelegation.delegate_principal_id == pid_subq
        )
        if voting_only:
            stmt = stmt.where(MeetingDelegation.delegate_voting.is_(True))
        return set((await self.session.execute(stmt)).scalars().all())

    async def assert_can_read(self, meeting_id: UUID, principal: Principal) -> None:
        """Guard read access to meeting details (detail/roster/agenda).

        Allowed for admin/``meeting.manage``, members + pool substitutes of the
        gremium, and delegation recipients of this meeting — the same visibility as
        the timeline. Prevents cross-tenant reads (roster carries names/emails)."""
        meeting = await self._get(meeting_id)  # 404 if unknown
        visible = await self._visible_gremium_ids(principal)
        if visible is None or meeting.gremium_id in visible:
            return
        if meeting_id in await self._delegated_meeting_ids(principal.sub):
            return
        raise ForbiddenError("not allowed to view this meeting")

    async def _visible_gremium_ids(self, principal: Principal) -> set[UUID] | None:
        """Gremien whose meetings the principal may see — ``None`` = ALL.

        Admin/``meeting.manage``/``meeting.view_all`` see everything; otherwise the
        gremien of membership (any role) plus substitute-pool gremien. Pool standing
        grants timeline visibility only — the live channel requires a concrete
        delegation (``is_participant``). ``meeting.view_all`` is the global, purely
        additive READ permission; managing/writing/voting stays gated separately."""
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
        """Gremien whose substitute pool contains ``sub``."""
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
        """Build the ``MeetingOut`` with the principal's four permission flags."""
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
