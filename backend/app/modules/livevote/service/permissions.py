"""The permission-flag serializer of a meeting.

The RBAC checks and the visibility scope are in `app.modules.meetings.rules`
(§S/backend/python/000650). This class adds the read model with the flags.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.auth.principal import Principal
from app.modules.livevote.schemas import MeetingOut, MeetingVoteOut
from app.modules.livevote.service.service_base import MeetingServiceBase
from app.modules.meetings.keepers import keeper_summaries
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.meetings.rules import MeetingRuleOps


class PermissionOps(MeetingRuleOps, MeetingServiceBase):
    """The meeting rules (`meetings.rules`) and the permission-flag serializer."""

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
        allowed = not await self._gremium_quorum_set(meeting.gremium_id)
        window = (await self._open_windows([meeting]))[meeting.id]
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
                public_join_allowed=allowed,
                window=window,
            )
        can_manage = await self.can_manage(meeting.gremium_id, principal)
        final = (
            await self.session.scalar(
                select(Protocol.status).where(Protocol.meeting_id == meeting.id)
            )
        ) == "final"
        return self._to_out(
            meeting,
            protocol_id,
            can_manage=can_manage,
            can_delete=self._can_delete(principal, can_manage=can_manage, final=final),
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
            public_join_allowed=allowed,
            window=window,
        )
