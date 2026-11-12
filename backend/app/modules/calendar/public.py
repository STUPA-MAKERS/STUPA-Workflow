"""The public calendar: the reads without a sign-in.

The public calendar shows two kinds of entry and no other: a Termin with the switch
"Öffentlich", and a meeting of a Gremium with ``protocols_public``. It never shows a
card, an Event or an entry of an external calendar.

A public Termin gives its title, its start, its end, its place and its description. It
never gives its creator, its invited Gremien and persons or its answers, so an entry
of a Termin has no Gremium.

A public meeting gives its title, its day, its times, the name of its Gremium and the
titles of its TOPs that are not internal. A meeting whose protocol is public
(`protocol.public.visible_clause`) also gives the id of that protocol. It never gives
an internal TOP, a text, the attendance, a vote or the live state.

Visibility fails closed: every read answers 404 for anything that is not public.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, time
from typing import Protocol as TypingProtocol
from typing import cast
from uuid import UUID

from pydantic import Field
from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.calendar.entries import PER_KIND, SEARCH_LIMIT, by_day, meeting_entry, nearest
from app.modules.calendar.ics import AppointmentEvent, MeetingEvent
from app.modules.calendar.models import Appointment
from app.modules.calendar.schemas import EntryOut
from app.modules.gremien.models import Gremium
from app.modules.meetings.agenda_service import title_of
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.protocol.public import visible_clause
from app.modules.site_config.features import Feature, feature_on
from app.shared.errors import NotFoundError
from app.shared.schemas import FrozenCamelModel
from app.shared.search import escape_like

logger = logging.getLogger("app.calendar")

#: The seconds that the server keeps the public feed.
FEED_TTL_SECONDS = 300
_FEED_KEY = "calendar:public-feed:v1"


class PublicGremiumOut(FrozenCamelModel, frozen=True):
    """A Gremium of the filter of the public calendar."""

    id: UUID
    name: str


class PublicAppointmentOut(FrozenCamelModel, frozen=True):
    """The public fields of a Termin. No creator, no invitation, no answer."""

    id: UUID
    title: str
    starts_on: date = Field(serialization_alias="startsOn")
    ends_on: date = Field(serialization_alias="endsOn")
    start_time: time | None = Field(default=None, serialization_alias="startTime")
    end_time: time | None = Field(default=None, serialization_alias="endTime")
    place: str | None = None
    description: str | None = None


class PublicMeetingOut(FrozenCamelModel, frozen=True):
    """The public fields of a meeting.

    ``tops`` holds the titles of the TOPs that are not internal, in the agenda order.
    ``protocolId`` is set when the public protocol of the meeting exists.
    """

    id: UUID
    title: str
    day: date
    start_time: time | None = Field(default=None, serialization_alias="startTime")
    end_time: time | None = Field(default=None, serialization_alias="endTime")
    gremium: str
    tops: tuple[str, ...] = ()
    protocol_id: UUID | None = Field(default=None, serialization_alias="protocolId")


class FeedCache(TypingProtocol):
    """The cache of the bytes of the public feed."""

    async def get(self) -> bytes | None:
        """Read the cached feed, or None when nothing is cached."""
        ...

    async def put(self, body: bytes) -> None:
        """Store the feed for `FEED_TTL_SECONDS`."""
        ...


class RedisFeedCache:
    """The feed cache on a shared ``redis.asyncio`` client.

    It fails open: Redis is only a cache, so a read error is "not cached" and a write
    error does nothing. The route then builds the feed from the database.
    """

    def __init__(self, client: object) -> None:
        """Bind the cache to the Redis client of the app."""
        self._client = client

    async def get(self) -> bytes | None:
        """Read the cached feed, or None when nothing is cached or Redis fails."""
        try:
            raw = await self._client.get(_FEED_KEY)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("public_feed_cache_read_failed", exc_info=True)
            return None
        return raw if isinstance(raw, bytes) else None

    async def put(self, body: bytes) -> None:
        """Store the feed for `FEED_TTL_SECONDS`. A Redis failure is ignored."""
        try:
            await self._client.set(_FEED_KEY, body, ex=FEED_TTL_SECONDS)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("public_feed_cache_write_failed", exc_info=True)


def appointment_entry(row: Appointment) -> EntryOut:
    """A public Termin as an entry, without a Gremium and without an answer."""
    return EntryOut(
        kind="appointment",
        id=row.id,
        title=row.title,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        start_time=row.start_time,
        end_time=row.end_time,
        place=row.place,
    )


def _in_gremien(gremium_ids: Sequence[UUID]) -> tuple[ColumnElement[bool], ...]:
    return (Meeting.gremium_id.in_(gremium_ids),) if gremium_ids else ()


class PublicCalendarService:
    """The reads of the public calendar, bound to one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the reads to the session of the request."""
        self.session = session

    async def gremien(self) -> tuple[PublicGremiumOut, ...]:
        """The Gremien whose meetings are public, by name."""
        rows = await self.session.execute(
            select(Gremium.id, Gremium.name)
            .where(Gremium.protocols_public.is_(True))
            .order_by(Gremium.name, Gremium.id)
        )
        return tuple(PublicGremiumOut(id=row[0], name=row[1]) for row in rows)

    async def _meetings(
        self, *conditions: ColumnElement[bool], newest: bool = False, limit: int | None = None
    ) -> list[tuple[Meeting, str]]:
        """The public meetings; none while `Sitzungen` is off."""
        if not await feature_on(self.session, Feature.MEETINGS):
            return []
        return [
            (row[0], row[1])
            for row in await self.session.execute(
                select(Meeting, Gremium.name)
                .join(Gremium, Gremium.id == Meeting.gremium_id)
                .where(Meeting.date.is_not(None), Gremium.protocols_public.is_(True), *conditions)
                .order_by(Meeting.date.desc() if newest else Meeting.date, Meeting.id)
                .limit(limit)
            )
        ]

    async def _appointments(
        self, *conditions: ColumnElement[bool], limit: int | None = None
    ) -> Sequence[Appointment]:
        return (
            await self.session.scalars(
                select(Appointment)
                .where(Appointment.public.is_(True), *conditions)
                .order_by(Appointment.starts_on, Appointment.id)
                .limit(limit)
            )
        ).all()

    async def between(
        self, start: date, end: date, gremium_ids: Sequence[UUID] = ()
    ) -> tuple[EntryOut, ...]:
        """The public entries with a day in the span, both ends included, sorted by day.

        A filter by Gremium keeps only the meetings of these Gremien, because a public
        Termin has no Gremium.
        """
        meetings = await self._meetings(
            Meeting.date >= start, Meeting.date <= end, *_in_gremien(gremium_ids)
        )
        termine = (
            ()
            if gremium_ids
            else await self._appointments(
                Appointment.starts_on <= end, Appointment.ends_on >= start
            )
        )
        return by_day(
            [
                *(meeting_entry(meeting, name) for meeting, name in meetings),
                *(appointment_entry(row) for row in termine),
            ]
        )

    async def search(self, q: str, today: date) -> tuple[EntryOut, ...]:
        """The public entries whose title holds ``q``, the nearest to today first.

        A Termin also matches by its place. A query of less than two characters finds
        nothing.
        """
        term = q.strip()
        if len(term) < 2:
            return ()
        pattern = f"%{escape_like(term)}%"
        meetings = await self._meetings(
            Meeting.title.ilike(pattern, escape="\\"), newest=True, limit=PER_KIND
        )
        termine = await self._appointments(
            or_(
                Appointment.title.ilike(pattern, escape="\\"),
                Appointment.place.ilike(pattern, escape="\\"),
            ),
            limit=PER_KIND,
        )
        return nearest(
            [
                *(meeting_entry(meeting, name) for meeting, name in meetings),
                *(appointment_entry(row) for row in termine),
            ],
            today,
            SEARCH_LIMIT,
        )

    async def appointment(self, appointment_id: UUID) -> PublicAppointmentOut:
        """The public fields of one Termin.

        Raises:
            NotFoundError: No Termin has the id, or the Termin is not public.
        """
        rows = await self._appointments(Appointment.id == appointment_id, limit=1)
        if not rows:
            raise NotFoundError("Unknown calendar entry.")
        row = rows[0]
        return PublicAppointmentOut(
            id=row.id,
            title=row.title,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            start_time=row.start_time,
            end_time=row.end_time,
            place=row.place,
            description=row.description,
        )

    async def meeting(self, meeting_id: UUID) -> PublicMeetingOut:
        """The public fields of one meeting.

        The title of a TOP with an application is the title of the application.

        Raises:
            NotFoundError: No meeting has the id, the meeting has no date, or its
                Gremium does not publish its protocols.
        """
        found = await self._meetings(Meeting.id == meeting_id, limit=1)
        if not found:
            raise NotFoundError("Unknown calendar entry.")
        meeting, gremium = found[0]
        tops = await self.session.execute(
            select(MeetingAgendaItem.title, Application.data)
            .outerjoin(Application, Application.id == MeetingAgendaItem.application_id)
            .where(
                MeetingAgendaItem.meeting_id == meeting.id,
                MeetingAgendaItem.non_public.is_(False),
            )
            .order_by(
                MeetingAgendaItem.position, MeetingAgendaItem.created_at, MeetingAgendaItem.id
            )
        )
        protocol_id = await self.session.scalar(
            select(Protocol.id)
            .join(Meeting, Meeting.id == Protocol.meeting_id)
            .join(Gremium, Gremium.id == Protocol.gremium_id)
            .where(Protocol.meeting_id == meeting.id, visible_clause())
            .limit(1)
        )
        return PublicMeetingOut(
            id=meeting.id,
            title=meeting.title,
            day=cast(date, meeting.date),
            start_time=meeting.start_time,
            end_time=meeting.end_time if meeting.start_time is not None else None,
            gremium=gremium,
            tops=tuple(title for title in (row[0] or title_of(row[1]) for row in tops) if title),
            protocol_id=protocol_id,
        )

    async def feed(self) -> tuple[tuple[MeetingEvent, ...], tuple[AppointmentEvent, ...]]:
        """Every public meeting and every public Termin as events of the feed.

        The events hold no organiser and no attendee.
        """
        meetings = await self._meetings()
        termine = await self._appointments()
        return (
            tuple(
                MeetingEvent(
                    uid=str(meeting.id),
                    title=meeting.title,
                    date=cast(date, meeting.date),
                    start_time=meeting.start_time,
                    end_time=meeting.end_time,
                    stamp=meeting.created_at,
                    gremium_name=name,
                )
                for meeting, name in meetings
            ),
            tuple(
                AppointmentEvent(
                    uid=str(row.id),
                    title=row.title,
                    starts_on=row.starts_on,
                    ends_on=row.ends_on,
                    start_time=row.start_time,
                    end_time=row.end_time,
                    stamp=row.updated_at,
                    place=row.place,
                    description=row.description,
                    sequence=row.sequence,
                )
                for row in termine
            ),
        )
