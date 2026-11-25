"""The Events of the Kalender and of the iCal feed (000486, F/collaboration/events/003033).

The calendar shows each Event with a start of a team of the person, like a Termin, and
a press opens the Event. An Event in each phase stays, because a settled Event still took
place.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.events.access import event_team_ids
from app.modules.events.models import Event
from app.modules.teams.members import team_name


async def events_between(
    session: AsyncSession,
    principal: Principal,
    *,
    start: date | None = None,
    end: date | None = None,
    pattern: str | None = None,
    limit: int | None = None,
) -> list[tuple[Event, str]]:
    """Return the Events with a start of the teams of the principal, with the team name.

    ``start`` and ``end`` keep the Events with a day in the span; an Event without an end
    takes one day. ``pattern`` is an ILIKE pattern for the name. Without a span the
    newest start comes first, for the search.
    """
    teams = await event_team_ids(session, principal)
    if not teams:
        return []
    names = team_name().subquery()
    last_day = func.coalesce(Event.ends_on, Event.starts_on)
    rows = await session.execute(
        select(Event, names.c[1])
        .join(names, names.c[0] == Event.team_id)
        .where(
            Event.team_id.in_(list(teams)),
            Event.starts_on.is_not(None),
            *((last_day >= start,) if start is not None else ()),
            *((Event.starts_on <= end,) if end is not None else ()),
            *((Event.title.ilike(pattern, escape="\\"),) if pattern is not None else ()),
        )
        .order_by(
            Event.starts_on if start is not None else Event.starts_on.desc(),
            Event.start_time.nulls_first(),
            Event.id,
        )
        .limit(limit)
    )
    return [(event, str(name or "")) for event, name in rows.tuples().all()]
