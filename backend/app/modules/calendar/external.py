"""The external calendars: the admin writes, the fetch of the worker and the reads.

An external calendar is an ICS feed that a holder of ``admin.calendars`` subscribed, for
all persons or for one team. The entries of a calendar for all are readable by each
signed-in person. The entries of a calendar of a team are readable by the members of the
team (F/collaboration/teams/003070), and by a person who reads the meetings of every
Gremium.

The API never fetches. A create, a change of the address and "Jetzt abrufen" set
``due_at`` to now, and the worker (`worker/calendars.py`) fetches every calendar whose
``due_at`` is over. `refresh` replaces the entries only after a good fetch: a failed
fetch keeps the entries of the last good one and stores the time and the cause.

No function here commits. The router and the worker own the transaction.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.calendar.external_feed import BERLIN, FeedEntry
from app.modules.calendar.external_fetch import FeedFetcher, FetchError
from app.modules.calendar.external_read import FeedReader, Read, read_feed
from app.modules.calendar.models import ExternalCalendar, ExternalEntry
from app.modules.calendar.schemas import (
    EntryOut,
    ExternalCalendarIn,
    ExternalCalendarOut,
    ExternalEntryOut,
)
from app.modules.meetings.rules import MeetingRules
from app.modules.teams.members import member_team_ids, team_names
from app.modules.teams.models import Team
from app.shared.errors import NotFoundError, ValidationProblem

#: The most calendars that one run of the worker fetches.
BATCH = 20


def external_entry(
    entry: ExternalEntry, calendar: ExternalCalendar, gremium_of: Mapping[UUID, UUID]
) -> EntryOut:
    """An external entry as an entry of the Kalender. Its source is the calendar name.

    ``gremium_of`` maps an inherent team to its Gremium, for the Gremium filter.
    """
    return EntryOut(
        kind="external",
        id=entry.id,
        title=entry.title,
        starts_on=entry.starts_on,
        ends_on=entry.ends_on,
        start_time=entry.start_time,
        end_time=entry.end_time,
        place=entry.place,
        source=calendar.name,
        gremium_ids=(
            (gremium_of[calendar.team_id],)
            if calendar.team_id is not None and calendar.team_id in gremium_of
            else ()
        ),
    )


def _row_values(calendar_id: UUID, entry: FeedEntry) -> dict[str, object]:
    return {
        "calendar_id": calendar_id,
        "title": entry.title,
        "starts_on": entry.starts_on,
        "ends_on": entry.ends_on,
        "start_time": entry.start_time,
        "end_time": entry.end_time,
        "place": entry.place,
        "description": entry.description,
    }


class ExternalCalendarService:
    """The external calendars, bound to one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to the session of the request or of the worker run."""
        self.session = session

    # ----- admin -----

    async def _out(self, rows: Sequence[ExternalCalendar]) -> tuple[ExternalCalendarOut, ...]:
        ids = [row.id for row in rows]
        counts: dict[UUID, int] = {
            found[0]: found[1]
            for found in await self.session.execute(
                select(ExternalEntry.calendar_id, func.count())
                .where(ExternalEntry.calendar_id.in_(ids))
                .group_by(ExternalEntry.calendar_id)
            )
        }
        names = await team_names(self.session, {row.team_id for row in rows if row.team_id})
        return tuple(
            ExternalCalendarOut(
                id=row.id,
                name=row.name,
                url=row.url,
                team_id=row.team_id,
                team_name=names.get(row.team_id) if row.team_id else None,
                interval_minutes=row.interval_minutes,
                last_attempt_at=row.last_attempt_at,
                last_success_at=row.last_success_at,
                last_error=row.last_error,
                entry_count=counts.get(row.id, 0),
            )
            for row in rows
        )

    async def _row(self, calendar_id: UUID) -> ExternalCalendar:
        row = await self.session.scalar(
            select(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError("Unknown calendar.")
        return row

    async def _check_team(self, team_id: UUID | None) -> None:
        if team_id is not None and await self.session.get(Team, team_id) is None:
            raise ValidationProblem("Unknown team.", code="calendar_team_unknown")

    async def listing(self) -> tuple[ExternalCalendarOut, ...]:
        """Every external calendar by name, with the state of its newest fetch."""
        rows = (
            await self.session.scalars(
                select(ExternalCalendar)
                .order_by(func.lower(ExternalCalendar.name), ExternalCalendar.id)
                .execution_options(populate_existing=True)
            )
        ).all()
        return await self._out(rows)

    async def one(self, calendar_id: UUID) -> ExternalCalendarOut:
        """One external calendar.

        Raises:
            NotFoundError: No calendar has the id.
        """
        return (await self._out([await self._row(calendar_id)]))[0]

    async def create(self, data: ExternalCalendarIn) -> ExternalCalendarOut:
        """Subscribe a calendar. It is due at once, so the worker fetches it next.

        Raises:
            ValidationProblem: The team does not exist.
        """
        await self._check_team(data.team_id)
        calendar_id = await self.session.scalar(
            insert(ExternalCalendar)
            .values(
                name=data.name.strip(),
                url=data.url,
                team_id=data.team_id,
                interval_minutes=data.interval_minutes,
            )
            .returning(ExternalCalendar.id)
        )
        return await self.one(calendar_id)  # type: ignore[arg-type]

    async def change(self, calendar_id: UUID, data: ExternalCalendarIn) -> ExternalCalendarOut:
        """Change a calendar. A new address makes it due at once.

        Raises:
            NotFoundError: No calendar has the id.
            ValidationProblem: The team does not exist.
        """
        row = await self._row(calendar_id)
        await self._check_team(data.team_id)
        await self.session.execute(
            update(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id)
            .values(
                name=data.name.strip(),
                url=data.url,
                team_id=data.team_id,
                interval_minutes=data.interval_minutes,
                due_at=func.now() if data.url != row.url else ExternalCalendar.due_at,
            )
        )
        return await self.one(calendar_id)

    async def remove(self, calendar_id: UUID) -> None:
        """Delete a calendar together with its entries.

        Raises:
            NotFoundError: No calendar has the id.
        """
        await self._row(calendar_id)
        await self.session.execute(
            delete(ExternalCalendar).where(ExternalCalendar.id == calendar_id)
        )

    async def request_fetch(self, calendar_id: UUID) -> ExternalCalendarOut:
        """Make a calendar due at once ("Jetzt abrufen").

        Raises:
            NotFoundError: No calendar has the id.
        """
        await self._row(calendar_id)
        await self.session.execute(
            update(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id)
            .values(due_at=func.now())
        )
        return await self.one(calendar_id)

    # ----- worker -----

    async def due(self, now: datetime) -> tuple[UUID, ...]:
        """The calendars whose next fetch is due, the longest waiting first."""
        return tuple(
            (
                await self.session.scalars(
                    select(ExternalCalendar.id)
                    .where(ExternalCalendar.due_at <= now)
                    .order_by(ExternalCalendar.due_at, ExternalCalendar.id)
                    .limit(BATCH)
                )
            ).all()
        )

    async def refresh(
        self,
        calendar_id: UUID,
        fetcher: FeedFetcher,
        now: datetime,
        reader: FeedReader = read_feed,
    ) -> bool:
        """Fetch one calendar and store the result. Return whether the fetch was good.

        The row is locked, so two workers never fetch the same calendar at once. A
        calendar that is gone, or that another run already moved on, gives False. The
        reader turns the bytes into entries in a process of its own with a time limit
        (§F/meetings/calendar/000974).
        """
        row = await self.session.scalar(
            select(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id, ExternalCalendar.due_at <= now)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        fetched = await fetcher.fetch(row.url)
        entries, error = await _read(
            fetched.data, fetched.error, now.astimezone(BERLIN).date(), reader
        )
        if entries is not None:
            await self.session.execute(
                delete(ExternalEntry).where(ExternalEntry.calendar_id == calendar_id)
            )
            if entries:
                await self.session.execute(
                    insert(ExternalEntry), [_row_values(calendar_id, e) for e in entries]
                )
        await self.session.execute(
            update(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id)
            .values(
                due_at=now + timedelta(minutes=row.interval_minutes),
                last_attempt_at=now,
                last_error=error,
                last_success_at=now if error is None else ExternalCalendar.last_success_at,
            )
        )
        return error is None

    # ----- reads -----

    async def _scope(self, principal: Principal) -> tuple[ColumnElement[bool], ...]:
        """A calendar of a team shows to its members (F/collaboration/teams/003070).

        A person who reads the meetings of every Gremium reads every calendar, as before.
        """
        visible, _ = await MeetingRules(self.session).meeting_read_scope(principal)
        if visible is None:
            return ()
        teams = await member_team_ids(self.session, principal)
        return (
            or_(
                ExternalCalendar.team_id.is_(None),
                ExternalCalendar.team_id.in_(teams),
            ),
        )

    async def _entries(
        self, principal: Principal, *conditions: ColumnElement[bool], limit: int | None = None
    ) -> list[tuple[ExternalEntry, ExternalCalendar]]:
        return [
            (found[0], found[1])
            for found in await self.session.execute(
                select(ExternalEntry, ExternalCalendar)
                .join(ExternalCalendar, ExternalCalendar.id == ExternalEntry.calendar_id)
                .where(*(await self._scope(principal)), *conditions)
                .order_by(ExternalEntry.starts_on, ExternalEntry.id)
                .limit(limit)
            )
        ]

    async def between(
        self, principal: Principal, start: date, end: date
    ) -> list[tuple[ExternalEntry, ExternalCalendar]]:
        """The readable entries with a day in the span, both ends included."""
        return await self._entries(
            principal, ExternalEntry.starts_on <= end, ExternalEntry.ends_on >= start
        )

    async def matching(
        self, principal: Principal, pattern: str, limit: int
    ) -> list[tuple[ExternalEntry, ExternalCalendar]]:
        """The readable entries whose title or place matches the LIKE pattern."""
        return await self._entries(
            principal,
            or_(
                ExternalEntry.title.ilike(pattern, escape="\\"),
                ExternalEntry.place.ilike(pattern, escape="\\"),
            ),
            limit=limit,
        )

    async def readable(self, principal: Principal) -> list[tuple[ExternalEntry, ExternalCalendar]]:
        """Every readable entry, for the personal feed."""
        return await self._entries(principal)

    async def entry(self, principal: Principal, entry_id: UUID) -> ExternalEntryOut:
        """One entry with the name of its calendar.

        Raises:
            NotFoundError: No entry has the id, or the caller does not read its calendar.
        """
        found = await self._entries(principal, ExternalEntry.id == entry_id, limit=1)
        if not found:
            raise NotFoundError("Unknown calendar entry.")
        row, calendar = found[0]
        return ExternalEntryOut(
            id=row.id,
            title=row.title,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            start_time=row.start_time,
            end_time=row.end_time,
            place=row.place,
            description=row.description,
            calendar=calendar.name,
        )


async def _read(
    data: bytes | None, error: FetchError | None, today: date, reader: FeedReader
) -> Read:
    """Turn the result of a fetch into the entries, or into the cause of the failure."""
    if data is None:
        return None, error or "unreachable"
    return await reader(data, today)
