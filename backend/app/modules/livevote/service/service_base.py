"""Shared base of the `MeetingService` ops classes.

This module holds the constructor and the lookup and serialization helpers. The
permissions, votes, listing, and lifecycle concerns all use them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.agenda_service import agenda_order, title_of
from app.modules.livevote.keepers import KeeperSummary
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingGuest
from app.modules.livevote.open_window import OpenWindow, load_meeting_settings, open_window
from app.modules.livevote.schemas import CurrentAgendaItemOut, MeetingOut, MeetingVoteOut
from app.modules.protocol.models import Protocol
from app.settings import get_settings
from app.shared.errors import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.auth.principal import Principal
    from app.modules.livevote.service.pubsub import BrokerPublisher

#: Per meeting: the number of agenda items and the current item.
AgendaSummary = tuple[int, CurrentAgendaItemOut | None]
#: Per meeting: the admitted and the pending guests.
GuestCounts = tuple[int, int]

#: The current agenda item of a meeting: its position, application and own title.
_Hit = tuple[int, UUID | None, str | None]


def _current_item(
    hit: _Hit | None, app_titles: dict[UUID, str | None]
) -> CurrentAgendaItemOut | None:
    """Describe the current agenda item; an item without an own title takes the application's."""
    match hit:
        case None:
            return None
        case (position, application_id, title):
            return CurrentAgendaItemOut(
                position=position,
                title=(
                    app_titles.get(application_id)
                    if application_id is not None and not title
                    else title
                ),
            )


class MeetingServiceBase:
    """Meeting operations bound to one `AsyncSession` and an optional publisher."""

    def __init__(self, session: AsyncSession, publisher: BrokerPublisher | None = None) -> None:
        """Bind the service to a session and an optional publisher."""
        self.session = session
        self.publisher = publisher

    @staticmethod
    def _can_delete(principal: Principal, *, can_manage: bool, final: bool) -> bool:
        """Mirror the delete gate of `LifecycleOps.check_deletable` for the read model.

        A final protocol is a signed and mailed document, so its meeting needs the
        global ``meeting.delete_finalized`` on top of ``canManage``.
        """
        return can_manage and (not final or principal.has("meeting.delete_finalized"))

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
        can_delete: bool = False,
        is_protokollant: bool = False,
        protokollant_name: str | None = None,
        gremium_name: str | None = None,
        votes: list[MeetingVoteOut] | None = None,
        agenda: AgendaSummary = (0, None),
        keepers: KeeperSummary | None = None,
        guests: GuestCounts = (0, 0),
        public_join_allowed: bool = True,
        window: OpenWindow | None = None,
    ) -> MeetingOut:
        """Build the meeting view for one principal.

        `canControl` marks the right to run the meeting: the protocol, the agenda items and
        the status. The protokollant and the session manager hold it, and the frontend gates
        the editor on this flag. The guest columns are read with `getattr`, because a read
        model of an older caller may lack them. The join code and the open requests go to
        the meeting lead only.
        """
        periods, planned = keepers if keepers is not None else ([], None)
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
            canControl=can_write,
            canManage=can_manage,
            canWrite=can_write,
            canManageVotes=can_manage_votes,
            canVote=can_vote,
            canFinalize=can_finalize,
            canDelete=can_delete,
            votes=votes or [],
            keeperPeriods=periods,
            plannedHandover=planned,
            publicJoin=bool(getattr(meeting, "public_join", False)),
            guestsMode=getattr(meeting, "guests_mode", None) or "vote",
            joinCode=getattr(meeting, "join_code", None) if can_manage else None,
            admittedGuests=guests[0],
            pendingGuests=guests[1] if can_manage else 0,
            publicJoinAllowed=public_join_allowed,
            opensAt=window.opens_at if window is not None else None,
            confirmUntil=window.confirm_until if window is not None else None,
        )

    async def _open_windows(self, meetings: Sequence[Meeting]) -> dict[UUID, OpenWindow | None]:
        """Return the open window of each meeting.

        One read of the settings row, and none when no planned meeting has a date.
        """
        if not any(m.status == "planned" and m.date is not None for m in meetings):
            return {m.id: None for m in meetings}
        settings = await load_meeting_settings(self.session)
        tz_name = get_settings().local_timezone
        return {m.id: open_window(m, settings, tz_name) for m in meetings}

    async def _guest_counts(self, meeting_ids: Sequence[UUID]) -> dict[UUID, GuestCounts]:
        """Count the admitted and the pending guests of each meeting, batched."""
        if not meeting_ids:
            return {}
        rows = (
            await self.session.execute(
                select(MeetingGuest.meeting_id, MeetingGuest.status, func.count())
                .where(
                    MeetingGuest.meeting_id.in_(list(meeting_ids)),
                    MeetingGuest.status.in_(("admitted", "pending")),
                )
                .group_by(MeetingGuest.meeting_id, MeetingGuest.status)
            )
        ).all()
        by_status = {(meeting_id, status): n for meeting_id, status, n in rows}
        return {
            meeting_id: (
                by_status.get((meeting_id, "admitted"), 0),
                by_status.get((meeting_id, "pending"), 0),
            )
            for meeting_id in dict.fromkeys(meeting_id for meeting_id, _, _ in rows)
        }

    async def _agenda_summaries(self, meetings: Sequence[Meeting]) -> dict[UUID, AgendaSummary]:
        """Count the agenda items of each meeting and describe its current item.

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
        by_meeting = {
            meeting_id: [row for row in rows if row[0] == meeting_id]
            for meeting_id in dict.fromkeys(row[0] for row in rows)
        }
        hits: dict[UUID, _Hit] = {
            meeting_id: (position, application_id, title)
            for meeting_id, items in by_meeting.items()
            for position, (_, item_id, application_id, title) in enumerate(items, start=1)
            if item_id == current.get(meeting_id)
        }
        app_titles = await self._application_titles(
            {app_id for _, app_id, _ in hits.values() if app_id is not None}
        )
        return {
            meeting.id: (
                len(by_meeting.get(meeting.id, ())),
                _current_item(hits.get(meeting.id), app_titles),
            )
            for meeting in meetings
        }

    async def _application_titles(self, app_ids: set[UUID]) -> dict[UUID, str | None]:
        """Return the title of each application, or nothing for no application."""
        if not app_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Application.id, Application.data).where(Application.id.in_(app_ids))
            )
        ).all()
        return {app_id: title_of(data) for app_id, data in rows}

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

    async def _gremium_quorum_set(self, gremium_id: UUID) -> bool:
        """Tell if the gremium sets a default quorum (then no public participation)."""
        row = await self.session.get(Gremium, gremium_id)
        return getattr(row, "quorum_percent", None) is not None

    async def _gremium_name_for(self, gremium_id: UUID | None) -> str | None:
        if gremium_id is None:
            return None
        row = await self.session.get(Gremium, gremium_id)
        return row.name if row is not None else None

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

    async def _protocol_id(self, meeting_id: UUID) -> UUID | None:
        """Return the `protocol.id` for the unique `meeting_id`, or `None`."""
        return (
            await self.session.execute(select(Protocol.id).where(Protocol.meeting_id == meeting_id))
        ).scalar_one_or_none()
