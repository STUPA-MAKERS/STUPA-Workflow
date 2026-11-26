"""The page "Veranstaltungen": the Events of the teams of the caller (003027, 003028).

The list holds only the Events of the teams of the caller (003026). The segments follow
the phases of the statuses (F/administration/admin/003036) and never name a status, so
each installation names its own steps.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event
from app.modules.events.rules import Segment
from app.modules.statuses.service import in_phase
from app.shared.search import dialect_of, trigram_rank

#: The status list of the Events.
LIST = "event"


@dataclass(frozen=True, slots=True)
class EventFilter:
    """The filter of the page "Veranstaltungen" (003028).

    Attributes:
        segment: The segment, else every Event.
        team_id: The chip Team.
        series_id: The chip Reihe.
        q: The search in the number, the name and the place.
    """

    segment: Segment | None = None
    team_id: uuid.UUID | None = None
    series_id: uuid.UUID | None = None
    q: str | None = None


def _day() -> ColumnElement[date | None]:
    """The day that decides between upcoming and past: the end, else the start."""
    return func.coalesce(Event.ends_on, Event.starts_on)


def segment_clause(segment: Segment, today: date) -> ColumnElement[bool]:
    """Build the rule of `rules.segment_of` as SQL."""
    match segment:
        case "upcoming":
            return and_(
                in_phase(Event.status, LIST, "open"), or_(_day().is_(None), _day() >= today)
            )
        case "past":
            return and_(in_phase(Event.status, LIST, "open"), _day() < today)
        case "done":
            return in_phase(Event.status, LIST, "done")
        case "void":
            return in_phase(Event.status, LIST, "void")


def _order(segment: Segment | None) -> tuple[Any, ...]:
    """The order of a segment: upcoming the earliest first, the others the newest first."""
    match segment:
        case "upcoming":
            return (Event.starts_on.asc().nulls_last(), Event.start_time.asc().nulls_first())
        case "past":
            return (_day().desc(),)
        case _:
            return (Event.starts_on.desc().nulls_last(),)


@dataclass(frozen=True, slots=True)
class EventListing:
    """The list of the page "Veranstaltungen", bound to an ``AsyncSession``."""

    session: AsyncSession
    today: date

    def _search(self, q: str | None) -> tuple[ColumnElement[bool], ColumnElement[Any]] | None:
        """Build the search clause and its rank, or None without a query.

        A person types the number as the page shows it, so the ``V-`` goes before the
        search reads the stored characters.
        """
        text = (q or "").strip()
        if not text:
            return None
        return trigram_rank(
            text.removeprefix("V-").removeprefix("v-") or text,
            [Event.number, Event.title, Event.place],
            dialect=dialect_of(self.session),
        )

    async def page(
        self,
        teams: Collection[uuid.UUID],
        wanted: EventFilter,
        *,
        limit: int,
        offset: int,
    ) -> tuple[list[Event], int]:
        """Return one page of the Events of ``teams`` and the total.

        An active search puts the best hit first.
        """
        if not teams:
            return [], 0
        search = self._search(wanted.q)
        optional = (
            segment_clause(wanted.segment, self.today) if wanted.segment is not None else None,
            Event.team_id == wanted.team_id if wanted.team_id is not None else None,
            Event.series_id == wanted.series_id if wanted.series_id is not None else None,
            search[0] if search is not None else None,
        )
        filters = [
            Event.team_id.in_(list(teams)),
            *(clause for clause in optional if clause is not None),
        ]
        total = await self.session.scalar(
            select(func.count()).select_from(select(Event.id).where(*filters).subquery())
        )
        order = (*_order(wanted.segment), Event.created_at.desc(), Event.id)
        rows = await self.session.scalars(
            select(Event)
            .where(*filters)
            .order_by(*((search[1].desc(), *order) if search is not None else order))
            .limit(limit)
            .offset(offset)
        )
        return list(rows), total or 0
