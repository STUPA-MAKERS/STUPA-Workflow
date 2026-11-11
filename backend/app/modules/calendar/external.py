"""The external calendars: the admin writes, the fetch of the worker and the reads.

An external calendar is an ICS feed that a holder of ``admin.calendars`` subscribed, for
all persons or for one Gremium. The entries of a calendar for all are readable by each
signed-in person. The entries of a calendar of a Gremium are readable by the persons who
read the meetings of that Gremium (`MeetingRules.meeting_read_scope`), so the Kalender
and the meeting list agree.

The API never fetches. A create, a change of the address and "Jetzt abrufen" set
``due_at`` to now, and the worker (`worker/calendars.py`) fetches every calendar whose
``due_at`` is over. `refresh` replaces the entries only after a good fetch: a failed
fetch keeps the entries of the last good one and stores the time and the cause.

No function here commits. The router and the worker own the transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.calendar.external_feed import BERLIN, FeedEntry, FeedError, parse_feed
from app.modules.calendar.external_fetch import FeedFetcher, FetchError
from app.modules.calendar.models import ExternalCalendar, ExternalEntry
from app.modules.calendar.schemas import (
    EntryOut,
    ExternalCalendarIn,
    ExternalCalendarOut,
    ExternalEntryOut,
)
from app.modules.gremien.models import Gremium
from app.modules.meetings.rules import MeetingRules
from app.shared.errors import NotFoundError, ValidationProblem

#: The most calendars that one run of the worker fetches.
BATCH = 20


def external_entry(entry: ExternalEntry, calendar: ExternalCalendar) -> EntryOut:
    """An external entry as an entry of the Kalender. Its source is the calendar name."""
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
        gremium_ids=(calendar.gremium_id,) if calendar.gremium_id is not None else (),
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
        names: dict[UUID, str] = {
            found[0]: found[1]
            for found in await self.session.execute(
                select(Gremium.id, Gremium.name).where(
                    Gremium.id.in_([row.gremium_id for row in rows if row.gremium_id])
                )
            )
        }
        return tuple(
            ExternalCalendarOut(
                id=row.id,
                name=row.name,
                url=row.url,
                gremium_id=row.gremium_id,
                gremium_name=names.get(row.gremium_id) if row.gremium_id else None,
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

    async def _check_gremium(self, gremium_id: UUID | None) -> None:
        if gremium_id is not None and await self.session.get(Gremium, gremium_id) is None:
            raise ValidationProblem("Unknown Gremium.", code="calendar_gremium_unknown")

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
            ValidationProblem: The Gremium does not exist.
        """
        await self._check_gremium(data.gremium_id)
        calendar_id = await self.session.scalar(
            insert(ExternalCalendar)
            .values(
                name=data.name.strip(),
                url=data.url,
                gremium_id=data.gremium_id,
                interval_minutes=data.interval_minutes,
            )
            .returning(ExternalCalendar.id)
        )
        return await self.one(calendar_id)  # type: ignore[arg-type]

    async def change(self, calendar_id: UUID, data: ExternalCalendarIn) -> ExternalCalendarOut:
        """Change a calendar. A new address makes it due at once.

        Raises:
            NotFoundError: No calendar has the id.
            ValidationProblem: The Gremium does not exist.
        """
        row = await self._row(calendar_id)
        await self._check_gremium(data.gremium_id)
        await self.session.execute(
            update(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id)
            .values(
                name=data.name.strip(),
                url=data.url,
                gremium_id=data.gremium_id,
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

    async def refresh(self, calendar_id: UUID, fetcher: FeedFetcher, now: datetime) -> bool:
        """Fetch one calendar and store the result. Return whether the fetch was good.

        The row is locked, so two workers never fetch the same calendar at once. A
        calendar that is gone, or that another run already moved on, gives False.
        """
        row = await self.session.scalar(
            select(ExternalCalendar)
            .where(ExternalCalendar.id == calendar_id, ExternalCalendar.due_at <= now)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        fetched = await fetcher.fetch(row.url)
        entries, error = _read(fetched.data, fetched.error, now.astimezone(BERLIN).date())
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
        visible, _ = await MeetingRules(self.session).meeting_read_scope(principal)
        return (
            ()
            if visible is None
            else (
                or_(
                    ExternalCalendar.gremium_id.is_(None),
                    ExternalCalendar.gremium_id.in_(visible),
                ),
            )
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


def _read(
    data: bytes | None, error: FetchError | None, today: date
) -> tuple[tuple[FeedEntry, ...] | None, FetchError | None]:
    """Turn the result of a fetch into the entries, or into the cause of the failure."""
    if data is None:
        return None, error or "unreachable"
    try:
        return parse_feed(data, today), None
    except FeedError:
        return None, "format"
