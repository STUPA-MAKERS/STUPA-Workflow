"""Shared base of the `MeetingService` ops classes.

This module holds the constructor and the lookup and serialization helpers. The
permissions, votes, listing, and lifecycle concerns all use them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.agenda_service import agenda_order, title_of
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.livevote.schemas import CurrentAgendaItemOut, MeetingOut, MeetingVoteOut
from app.modules.protocol.models import Protocol
from app.shared.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.livevote.service.pubsub import BrokerPublisher

# Per meeting: the number of agenda items and the current item (A2).
AgendaSummary = tuple[int, CurrentAgendaItemOut | None]


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
        can_finalize: bool = False,
        is_protokollant: bool = False,
        protokollant_name: str | None = None,
        gremium_name: str | None = None,
        votes: list[MeetingVoteOut] | None = None,
        agenda: AgendaSummary = (0, None),
    ) -> MeetingOut:
        return MeetingOut(
            id=meeting.id,
            gremiumId=meeting.gremium_id,
            gremiumName=gremium_name,
            title=meeting.title,
            date=meeting.date,
            startTime=meeting.start_time,
            endTime=meeting.end_time,
            startedAt=meeting.started_at,
            closedAt=meeting.closed_at,
            status=meeting.status,  # type: ignore[arg-type]
            activeApplicationId=meeting.active_application_id,
            currentAgendaItemId=meeting.current_agenda_item_id,
            currentAgendaItem=agenda[1],
            agendaItemCount=agenda[0],
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
            canFinalize=can_finalize,
            votes=votes or [],
        )

    async def _agenda_summaries(self, meetings: Sequence[Meeting]) -> dict[UUID, AgendaSummary]:
        """Count the agenda items of each meeting and describe its current item (A2).

        Two batched queries for any number of meetings: the agenda items in agenda
        order, then the titles of the applications behind the current items. The
        position is the 1-based number of the item in the agenda order, as the agenda
        list shows it.
        """
        if not meetings:
            return {}
        rows = (
            await self.session.execute(
                select(
                    MeetingAgendaItem.meeting_id,
                    MeetingAgendaItem.id,
                    MeetingAgendaItem.application_id,
                    MeetingAgendaItem.title,
                )
                .where(MeetingAgendaItem.meeting_id.in_([m.id for m in meetings]))
                .order_by(MeetingAgendaItem.meeting_id, *agenda_order())
            )
        ).all()
        current = {m.id: m.current_agenda_item_id for m in meetings}
        counts: dict[UUID, int] = {}
        hits: dict[UUID, tuple[int, UUID | None, str | None]] = {}
        for meeting_id, item_id, application_id, title in rows:
            counts[meeting_id] = counts.get(meeting_id, 0) + 1
            if item_id == current.get(meeting_id):
                hits[meeting_id] = (counts[meeting_id], application_id, title)
        app_ids = {app_id for _, app_id, _ in hits.values() if app_id is not None}
        app_titles: dict[UUID, str | None] = {}
        if app_ids:
            app_titles = {
                app_id: title_of(data)
                for app_id, data in (
                    await self.session.execute(
                        select(Application.id, Application.data).where(
                            Application.id.in_(app_ids)
                        )
                    )
                ).all()
            }
        out: dict[UUID, AgendaSummary] = {}
        for meeting in meetings:
            hit = hits.get(meeting.id)
            item: CurrentAgendaItemOut | None = None
            if hit is not None:
                position, application_id, title = hit
                if application_id is not None:
                    title = app_titles.get(application_id)
                item = CurrentAgendaItemOut(position=position, title=title)
            out[meeting.id] = (counts.get(meeting.id, 0), item)
        return out

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

    async def _get(self, meeting_id: UUID, *, for_update: bool = False) -> Meeting:
        """Load a meeting by id.

        ``for_update`` locks the meeting row until the commit and reads the current
        values again. A status change, an agenda change and a vote open all take this
        lock first, so they run one after the other (O12, O25).

        Raises:
            NotFoundError: No meeting has this id.
        """
        stmt = select(Meeting).where(Meeting.id == meeting_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _protocol_id(self, meeting_id: UUID) -> UUID | None:
        """Return the `protocol.id` for the unique `meeting_id`, or `None`."""
        return (
            await self.session.execute(select(Protocol.id).where(Protocol.meeting_id == meeting_id))
        ).scalar_one_or_none()
