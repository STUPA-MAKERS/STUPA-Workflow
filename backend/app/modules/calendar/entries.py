"""The entries of the Kalender page: meetings, due cards, Events, Termine, external entries.

Each kind is read under the rule of its own module, so the Kalender never shows an
entry that the list of that module does not show: the meetings through the read scope
of the meeting list (`MeetingRules.meeting_read_scope`), the cards and the Events
through the board scope of the to-dos, the Termine through `appointments.readable`,
and the external entries through the scope of their calendar (`external`).

The filter "Nur meine" limits the cards and the Events to the assigned ones and the
Termine to those that the caller created or is invited to. The meetings and the
external entries stay, because neither has a person that it belongs to.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, time
from typing import cast
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.calendar import rules
from app.modules.calendar.appointments import AppointmentService, Loaded, my_answer
from app.modules.calendar.external import ExternalCalendarService, external_entry
from app.modules.calendar.rules import Viewer
from app.modules.calendar.schemas import EntryOut
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.meetings.rules import MeetingRules
from app.modules.site_config.features import Feature, feature_on
from app.modules.todos.models import TodoBoard, TodoCard, TodoCardEvent
from app.modules.todos.service import TodoService
from app.shared.search import escape_like

#: The hits of one kind that a search reads, and the hits that it returns.
PER_KIND = 20
SEARCH_LIMIT = 30


def meeting_entry(meeting: Meeting, gremium_name: str) -> EntryOut:
    """A dated meeting as an entry. A meeting takes one day."""
    day = cast(date, meeting.date)
    return EntryOut(
        kind="meeting",
        id=meeting.id,
        title=meeting.title,
        starts_on=day,
        ends_on=day,
        start_time=meeting.start_time,
        end_time=meeting.end_time if meeting.start_time is not None else None,
        source=gremium_name,
        gremium_ids=(meeting.gremium_id,),
    )


def card_entry(card: TodoCard, board: TodoBoard, mine: bool) -> EntryOut:
    """An open card as an entry on its due date."""
    due = cast(date, card.due_date)
    return EntryOut(
        kind="card",
        id=card.id,
        title=card.title,
        starts_on=due,
        ends_on=due,
        source=board.name,
        gremium_ids=_board_gremien(board),
        mine=mine,
    )


def event_entry(card: TodoCard, board: TodoBoard, event: TodoCardEvent, mine: bool) -> EntryOut:
    """An Event as an entry from its start to its end, with its times.

    An Event without an end takes a day. An end time shows only with a start time.
    """
    start = cast(date, event.starts_on)
    return EntryOut(
        kind="event",
        id=card.id,
        title=card.title,
        starts_on=start,
        ends_on=max(event.ends_on or start, start),
        start_time=event.start_time,
        end_time=event.end_time if event.start_time is not None else None,
        place=event.place,
        source=board.name,
        gremium_ids=_board_gremien(board),
        mine=mine,
    )


def appointment_entry(viewer: Viewer, item: Loaded, gremium_names: dict[UUID, str]) -> EntryOut:
    """A Termin as an entry. Its source is the first invited Gremium by name."""
    row = item.row
    names = sorted(
        (gremium_names[gid] for gid in item.targets.gremium_ids if gid in gremium_names),
        key=str.casefold,
    )
    return EntryOut(
        kind="appointment",
        id=row.id,
        title=row.title,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        start_time=row.start_time,
        end_time=row.end_time,
        place=row.place,
        source=names[0] if names else None,
        gremium_ids=tuple(sorted(item.targets.gremium_ids, key=str)),
        mine=rules.is_creator(viewer, row.creator_id) or rules.is_invited(viewer, item.targets),
        my_answer=my_answer(viewer, item),
    )


def _board_gremien(board: TodoBoard) -> tuple[UUID, ...]:
    return (board.gremium_id,) if board.gremium_id is not None else ()


def by_day(entries: Sequence[EntryOut]) -> tuple[EntryOut, ...]:
    """Sort the entries by day and time. An entry without a time comes first on its day."""
    return tuple(
        sorted(
            entries,
            key=lambda e: (
                e.starts_on,
                e.start_time is not None,
                e.start_time or time.min,
                e.title,
            ),
        )
    )


def nearest(entries: Sequence[EntryOut], today: date, limit: int) -> tuple[EntryOut, ...]:
    """The hits of a search, the entry nearest to today first."""
    return tuple(
        sorted(entries, key=lambda e: (abs((e.starts_on - today).days), e.starts_on, e.title))
    )[:limit]


class CalendarEntries:
    """The reads of the Kalender page, bound to one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the reads to the session of the request."""
        self.session = session

    @property
    def appointments(self) -> AppointmentService:
        """The Termin reads on the same session."""
        return AppointmentService(self.session)

    async def _meetings(
        self,
        principal: Principal,
        *conditions: ColumnElement[bool],
        newest: bool,
        limit: int | None,
    ) -> list[EntryOut]:
        """The meetings the principal may read; none while `Sitzungen` is off."""
        if not await feature_on(self.session, Feature.MEETINGS):
            return []
        visible, delegated = await MeetingRules(self.session).meeting_read_scope(principal)
        scope = (
            ()
            if visible is None
            else (or_(Meeting.gremium_id.in_(visible), Meeting.id.in_(delegated)),)
        )
        rows = (
            await self.session.execute(
                select(Meeting, Gremium.name)
                .join(Gremium, Gremium.id == Meeting.gremium_id)
                .where(Meeting.date.is_not(None), *scope, *conditions)
                .order_by(Meeting.date.desc() if newest else Meeting.date, Meeting.id)
                .limit(limit)
            )
        ).all()
        return [meeting_entry(meeting, name) for meeting, name in rows]

    async def _appointment_entries(
        self, viewer: Viewer, loaded: Sequence[Loaded]
    ) -> list[EntryOut]:
        names = await self.appointments.gremium_names(loaded)
        return [appointment_entry(viewer, item, names) for item in loaded]

    async def between(
        self, principal: Principal, start: date, end: date, *, only_mine: bool = False
    ) -> tuple[EntryOut, ...]:
        """The entries with a day in the span, both ends included, sorted by day.

        The meetings stay out while `Sitzungen` is off, the cards and the Events while
        `Boards` is off.
        """
        viewer = await self.appointments.viewer(principal)
        todos = TodoService(self.session)
        boards_on = await feature_on(self.session, Feature.TODOS)
        meetings = await self._meetings(
            principal, Meeting.date >= start, Meeting.date <= end, newest=False, limit=None
        )
        cards = (
            await todos.calendar_due_between(principal, start=start, end=end, only_mine=only_mine)
            if boards_on
            else []
        )
        events = (
            await todos.calendar_events_between(
                principal, start=start, end=end, only_mine=only_mine
            )
            if boards_on
            else []
        )
        termine = await self.appointments.between(viewer, start, end, only_mine=only_mine)
        external = await ExternalCalendarService(self.session).between(principal, start, end)
        return by_day(
            [
                *meetings,
                *(card_entry(card, board, mine) for card, board, mine in cards),
                *(event_entry(card, board, event, mine) for card, board, event, mine in events),
                *(await self._appointment_entries(viewer, termine)),
                *(external_entry(entry, calendar) for entry, calendar in external),
            ]
        )

    async def search(self, principal: Principal, q: str, today: date) -> tuple[EntryOut, ...]:
        """The entries of every month whose title holds ``q``, the nearest to today first.

        A Termin and an external entry also match by their place. A query of less than
        two characters finds nothing.
        """
        term = q.strip()
        if len(term) < 2:
            return ()
        pattern = f"%{escape_like(term)}%"
        viewer = await self.appointments.viewer(principal)
        todos = TodoService(self.session)
        meetings = await self._meetings(
            principal, Meeting.title.ilike(pattern, escape="\\"), newest=True, limit=PER_KIND
        )
        boards_on = await feature_on(self.session, Feature.TODOS)
        cards = (
            await todos.calendar_due_between(principal, pattern=pattern, limit=PER_KIND)
            if boards_on
            else []
        )
        events = (
            await todos.calendar_events_between(principal, pattern=pattern, limit=PER_KIND)
            if boards_on
            else []
        )
        termine = await self.appointments.matching(viewer, pattern, PER_KIND)
        external = await ExternalCalendarService(self.session).matching(
            principal, pattern, PER_KIND
        )
        return nearest(
            [
                *meetings,
                *(card_entry(card, board, mine) for card, board, mine in cards),
                *(event_entry(card, board, event, mine) for card, board, event, mine in events),
                *(await self._appointment_entries(viewer, termine)),
                *(external_entry(entry, calendar) for entry, calendar in external),
            ],
            today,
            SEARCH_LIMIT,
        )
