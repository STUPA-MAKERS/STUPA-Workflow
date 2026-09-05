"""Shared base of the `MeetingService` ops classes.

This module holds the constructor and the lookup and serialization helpers. The
permissions, votes, listing, and lifecycle concerns all use them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.models import Gremium
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.models import Meeting
from app.modules.livevote.schemas import MeetingOut, MeetingVoteOut
from app.modules.protocol.models import Protocol
from app.shared.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.livevote.service.pubsub import BrokerPublisher


class MeetingServiceBase:
    """Meeting operations bound to one `AsyncSession` and an optional publisher."""

    def __init__(self, session: AsyncSession, publisher: BrokerPublisher | None = None) -> None:
        self.session = session
        self.publisher = publisher

    @staticmethod
    def _to_out(
        meeting: Meeting,
        protocol_id: UUID | None = None,
        *,
        can_manage: bool = False,
        can_write: bool = False,
        can_manage_votes: bool = False,
        can_vote: bool = False,
        is_protokollant: bool = False,
        protokollant_name: str | None = None,
        gremium_name: str | None = None,
        votes: list[MeetingVoteOut] | None = None,
    ) -> MeetingOut:
        return MeetingOut(
            id=meeting.id,
            gremiumId=meeting.gremium_id,
            gremiumName=gremium_name,
            title=meeting.title,
            date=meeting.date,
            startTime=meeting.start_time,
            endTime=meeting.end_time,
            closedAt=meeting.closed_at,
            status=meeting.status,  # type: ignore[arg-type]
            activeApplicationId=meeting.active_application_id,
            currentAgendaItemId=meeting.current_agenda_item_id,
            protocolId=protocol_id,
            createdAt=meeting.created_at,
            protokollantId=meeting.protokollant_id,
            protokollantName=protokollant_name,
            isProtokollant=is_protokollant,
            # `canControl` marks the right to run the meeting: the protocol, the
            # agenda items, and the status. The protokollant and the session manager
            # hold it. The frontend gates the editor on this flag.
            canControl=can_write,
            canManage=can_manage,
            canWrite=can_write,
            canManageVotes=can_manage_votes,
            canVote=can_vote,
            votes=votes or [],
        )

    async def _principal_id(self, sub: str) -> UUID | None:
        """Return the `principal.id` for an OIDC `sub`, used for the protokollant check."""
        return (
            await self.session.execute(select(PrincipalRow.id).where(PrincipalRow.sub == sub))
        ).scalar_one_or_none()

    @staticmethod
    async def _name_for(session: AsyncSession, principal_id: UUID | None) -> str | None:
        if principal_id is None:
            return None
        row = await session.get(PrincipalRow, principal_id)
        return (row.display_name or row.email) if row is not None else None

    async def _gremium_name_for(self, gremium_id: UUID | None) -> str | None:
        if gremium_id is None:
            return None
        row = await self.session.get(Gremium, gremium_id)
        return row.name if row is not None else None

    async def _get(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _protocol_id(self, meeting_id: UUID) -> UUID | None:
        """Return the `protocol.id` for the unique `meeting_id`, or `None`."""
        return (
            await self.session.execute(select(Protocol.id).where(Protocol.meeting_id == meeting_id))
        ).scalar_one_or_none()
