"""Service of the Veranstaltungen: reads, create, change, status change, delete and series.

Each read and write needs a member of the team of the Event (003026); a person who is
not a member gets 404, so the answer does not tell that the Event exists. The service
does not commit; the router owns the transaction. Each write raises the version and
emits its webhook event (003034).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.events import facts
from app.modules.events.access import event_team_ids
from app.modules.events.models import Event, format_event_number
from app.modules.events.rules import dates_problem, shop_valid
from app.modules.events.schemas import (
    EventCreate,
    EventDecisionOut,
    EventDetailOut,
    EventEditionOut,
    EventOut,
    EventRefOut,
    EventTeamOut,
    EventTotalsOut,
    EventUpdate,
    SeriesOut,
)
from app.modules.events.webhook_fields import emit_event_event
from app.modules.statuses.service import StatusReader, in_phase
from app.modules.teams.members import team_names
from app.modules.todos.models import TodoEventSeries
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.search import escape_like

#: The status list of the Events (F/administration/admin/003035).
LIST = "event"
#: The fields that a change can set, as wire name and column name.
_FIELDS: tuple[tuple[str, str], ...] = (
    ("teamId", "team_id"),
    ("title", "title"),
    ("descriptionMd", "description_md"),
    ("startsOn", "starts_on"),
    ("startTime", "start_time"),
    ("endsOn", "ends_on"),
    ("endTime", "end_time"),
    ("place", "place"),
    ("participants", "participants"),
    ("seriesId", "series_id"),
    ("shopUrl", "shop_url"),
)
#: The fields that a change must not clear.
_REQUIRED: frozenset[str] = frozenset({"teamId", "title"})
#: The most options of the picker and of the series.
PICKER_MAX = 50


def _refused(code: str, field_name: str, msg: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field_name, "msg": msg}])


def totals_out(value: facts.Totals) -> EventTotalsOut:
    """The totals as decimal strings with two places."""
    return EventTotalsOut(
        requested=facts.balance_text(value.requested),
        approved=facts.balance_text(value.approved),
        expenses=facts.balance_text(value.expenses),
        income=facts.balance_text(value.income),
        balance=facts.balance_text(value.balance),
    )


def _decision_out(value: facts.Decision) -> EventDecisionOut:
    return EventDecisionOut(
        kind=value.kind,  # type: ignore[arg-type]
        targetId=value.target_id,
        title=value.title,
        decidedAt=value.decided_at,
        meetingTitle=value.meeting_title,
        result=value.result,
        amount=facts.balance_text(value.amount) if value.amount is not None else None,
        conditions=list(value.conditions),
    )


def _row_values(row: Event) -> dict[str, Any]:
    """The columns of an Event that its views share."""
    return {
        "id": row.id,
        "number": format_event_number(row.number),
        "teamId": row.team_id,
        "status": row.status,
        "title": row.title,
        "descriptionMd": row.description_md,
        "startsOn": row.starts_on,
        "startTime": row.start_time,
        "endsOn": row.ends_on,
        "endTime": row.end_time,
        "place": row.place,
        "participants": row.participants,
        "seriesId": row.series_id,
        "shopUrl": row.shop_url,
        "version": row.version,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


@dataclass(frozen=True, slots=True)
class EventService:
    """The Events as one request sees them.

    Attributes:
        session: The database session.
        today: The current day in the local time zone, for the segments.
    """

    session: AsyncSession
    today: date
    _teams: dict[str, frozenset[uuid.UUID]] = field(default_factory=dict)

    async def teams(self, principal: Principal) -> frozenset[uuid.UUID]:
        """Return the teams whose Events the principal reads and writes (cached)."""
        if principal.sub not in self._teams:
            self._teams[principal.sub] = await event_team_ids(self.session, principal)
        return self._teams[principal.sub]

    async def team_options(self, principal: Principal) -> list[EventTeamOut]:
        """Return the teams of the caller by name: the options of the field Team."""
        names = await team_names(self.session, await self.teams(principal))
        return [
            EventTeamOut(id=team_id, name=name)
            for team_id, name in sorted(names.items(), key=lambda item: item[1].lower())
        ]

    async def get(self, event_id: uuid.UUID, principal: Principal) -> Event:
        """Return an Event of a team of the caller.

        Raises:
            NotFoundError: No Event has this id, or the caller is not a member of its team.
        """
        row = await self.session.get(Event, event_id)
        if row is None or row.team_id not in await self.teams(principal):
            raise NotFoundError(f"event {event_id} not found")
        return row

    async def _actor(self, principal: Principal) -> uuid.UUID | None:
        return await self.session.scalar(
            select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
        )

    async def _check_team(self, team_id: uuid.UUID, principal: Principal) -> None:
        """Refuse a team of which the caller is not a member (003026).

        Raises:
            ForbiddenError: ``event_team_forbidden`` (HTTP 403).
        """
        if team_id not in await self.teams(principal):
            raise ForbiddenError(
                "The person is not a member of the team.", code="event_team_forbidden"
            )

    async def _check_series(self, series_id: uuid.UUID | None) -> None:
        if series_id is not None and await self.session.get(TodoEventSeries, series_id) is None:
            raise _refused("series_not_found", "seriesId", "The series was not found.")

    @staticmethod
    def _check_shop(url: str | None) -> None:
        if url and not shop_valid(url):
            raise _refused(
                "event_url_invalid", "shopUrl", "The shop must be an http or https address."
            )

    async def create(self, payload: EventCreate, principal: Principal) -> Event:
        """Create an Event in a team of the caller with the start status of the list.

        Raises:
            ForbiddenError: The caller is not a member of the team.
            ValidationProblem: The shop is no http or https address (``event_url_invalid``),
                the series is unknown or the status is not in the list.
        """
        await self._check_team(payload.team_id, principal)
        self._check_shop(payload.shop_url)
        await self._check_series(payload.series_id)
        statuses = StatusReader(self.session)
        status = await statuses.require(LIST, payload.status or await statuses.start_key(LIST))
        row = Event(
            id=uuid.uuid4(),
            team_id=payload.team_id,
            status=status.key,
            title=payload.title,
            description_md=payload.description_md or None,
            starts_on=payload.starts_on,
            start_time=payload.start_time,
            ends_on=payload.ends_on,
            end_time=payload.end_time,
            place=payload.place or None,
            participants=payload.participants,
            series_id=payload.series_id,
            shop_url=payload.shop_url or None,
            version=1,
            created_by=await self._actor(principal),
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        await emit_event_event(self.session, row, "event.created")
        return row

    @staticmethod
    def _check_version(row: Event, version: int) -> None:
        """Refuse a write that read an older version (003023).

        Raises:
            ConflictError: ``event_version_conflict`` (HTTP 409).
        """
        if row.version != version:
            raise ConflictError(
                "A different person changed the Event.", code="event_version_conflict"
            )

    async def _save(self, row: Event, values: Mapping[str, object]) -> Event:
        for col, value in {**values, "version": row.version + 1}.items():
            setattr(row, col, value)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update(
        self, event_id: uuid.UUID, payload: EventUpdate, principal: Principal
    ) -> Event:
        """Change the fields that the body names.

        Raises:
            NotFoundError: The caller does not read the Event.
            ConflictError: A different version is current.
            ForbiddenError: The new team is not a team of the caller.
            ValidationProblem: A required field is empty, the dates do not fit, the shop is
                refused or the series is unknown.
        """
        row = await self.get(event_id, principal)
        self._check_version(row, payload.version)
        sent = payload.model_dump(by_alias=True, exclude_unset=True)
        values = {
            col: (None if sent[key] == "" else sent[key]) for key, col in _FIELDS if key in sent
        }
        for key, col in _FIELDS:
            if key in _REQUIRED and col in values and values[col] is None:
                raise _refused(f"event_{col}_required", key, "The field is required.")
        merged = {col: getattr(row, col) for _key, col in _FIELDS} | values
        problem = dates_problem(
            merged["starts_on"], merged["start_time"], merged["ends_on"], merged["end_time"]
        )
        if problem is not None:
            raise _refused(problem[0], problem[1], "The dates of the Event do not fit.")
        team = values.get("team_id")
        if isinstance(team, uuid.UUID) and team != row.team_id:
            await self._check_team(team, principal)
        self._check_shop(values.get("shop_url"))
        if "series_id" in values:
            await self._check_series(values["series_id"])
        saved = await self._save(row, values)
        await emit_event_event(self.session, saved, "event.updated")
        return saved

    async def set_status(
        self, event_id: uuid.UUID, status: str, version: int, principal: Principal
    ) -> Event:
        """Set a status of the list; each status follows each other one (003025).

        Raises:
            NotFoundError: The caller does not read the Event.
            ConflictError: A different version is current.
            ValidationProblem: The status is not in the list (``status_unknown``).
        """
        row = await self.get(event_id, principal)
        self._check_version(row, version)
        target = await StatusReader(self.session).require(LIST, status)
        previous = row.status
        saved = await self._save(row, {"status": target.key})
        if previous != target.key:
            await emit_event_event(self.session, saved, "event.status_changed", previous=previous)
        return saved

    async def delete(self, event_id: uuid.UUID, principal: Principal) -> None:
        """Delete an Event; the trigger of ``link`` drops its links (003033).

        Raises:
            NotFoundError: The caller does not read the Event.
        """
        row = await self.get(event_id, principal)
        await emit_event_event(self.session, row, "event.deleted")
        await self.session.delete(row)
        await self.session.flush()

    async def _series_names(self, rows: Sequence[Event]) -> Mapping[uuid.UUID, str]:
        return await facts.series_names(self.session, (row.series_id for row in rows))

    async def views(self, rows: Sequence[Event]) -> list[EventOut]:
        """Build the list views of the rows with one read per kind for the whole page."""
        names = await team_names(self.session, {row.team_id for row in rows})
        series = await self._series_names(rows)
        sums = await facts.totals(self.session, [row.id for row in rows])
        phases = await StatusReader(self.session).phases(LIST)
        return [
            EventOut.model_validate(
                {
                    **_row_values(row),
                    "teamName": names.get(row.team_id),
                    "phase": phases.get(row.status, "open"),
                    "seriesName": series.get(row.series_id) if row.series_id else None,
                    "totals": totals_out(sums[row.id]),
                }
            )
            for row in rows
        ]

    async def detail(self, row: Event, principal: Principal) -> EventDetailOut:
        """Build the detail: the fields, the totals, the decisions and the series (003029)."""
        base = (await self.views([row]))[0]
        teams = await self.teams(principal)
        others, hidden = await facts.editions(self.session, row, Event.team_id.in_(list(teams)))
        sums = await facts.totals(self.session, [other.id for other in others])
        return EventDetailOut.model_validate(
            {
                **base.model_dump(by_alias=True),
                "decisions": [
                    _decision_out(value) for value in await facts.decisions(self.session, row.id)
                ],
                "editions": [
                    EventEditionOut(
                        id=other.id,
                        number=format_event_number(other.number),
                        title=other.title,
                        status=other.status,
                        startsOn=other.starts_on,
                        endsOn=other.ends_on,
                        startTime=other.start_time,
                        endTime=other.end_time,
                        totals=totals_out(sums[other.id]),
                    )
                    for other in others
                ],
                "hiddenEditions": hidden,
            }
        )

    async def refs(self, q: str | None, principal: Principal) -> list[EventRefOut]:
        """The Events in the phase ``open`` that the caller writes: the options of the picker.

        The picker ``Veranstaltung`` of a Buchung lists only these (003033).
        """
        teams = await self.teams(principal)
        if not teams:
            return []
        term = (q or "").strip()
        titled = (Event.title.ilike(f"%{escape_like(term)}%", escape="\\"),) if term else ()
        rows = (
            await self.session.scalars(
                select(Event)
                .where(
                    Event.team_id.in_(list(teams)), in_phase(Event.status, LIST, "open"), *titled
                )
                .order_by(Event.starts_on.desc().nulls_first(), Event.created_at.desc())
                .limit(PICKER_MAX)
            )
        ).all()
        names = await team_names(self.session, {row.team_id for row in rows})
        return [
            EventRefOut(
                id=row.id,
                number=format_event_number(row.number),
                title=row.title,
                teamName=names.get(row.team_id),
                startsOn=row.starts_on,
                endsOn=row.ends_on,
                startTime=row.start_time,
                endTime=row.end_time,
            )
            for row in rows
        ]

    async def series(self, q: str | None) -> list[SeriesOut]:
        """List the series by name (at most 50), filtered by ``q``."""
        term = (q or "").strip()
        named = (TodoEventSeries.name.ilike(f"%{escape_like(term)}%", escape="\\"),) if term else ()
        rows = (
            await self.session.scalars(
                select(TodoEventSeries)
                .where(*named)
                .order_by(func.lower(TodoEventSeries.name))
                .limit(PICKER_MAX)
            )
        ).all()
        return [SeriesOut(id=row.id, name=row.name) for row in rows]

    async def create_series(self, name: str, principal: Principal) -> SeriesOut:
        """Create a series; its name is unique, case ignored (000483).

        Each member of a team creates a series, because each member creates an Event.

        Raises:
            ForbiddenError: ``event_team_forbidden`` without a team (HTTP 403).
            ValidationProblem: ``series_name_blank`` (HTTP 422).
            ConflictError: ``series_exists`` (HTTP 409).
        """
        if not await self.teams(principal):
            raise ForbiddenError("The person is in no team.", code="event_team_forbidden")
        value = name.strip()
        if not value:
            raise _refused("series_name_blank", "name", "The name is empty.")
        taken = await self.session.scalar(
            select(TodoEventSeries.id).where(func.lower(TodoEventSeries.name) == value.lower())
        )
        if taken is not None:
            raise ConflictError("A series with this name exists.", code="series_exists")
        row = TodoEventSeries(id=uuid.uuid4(), name=value, created_by=await self._actor(principal))
        self.session.add(row)
        await self.session.flush()
        return SeriesOut(id=row.id, name=row.name)

    async def readable_ids(
        self, ids: Collection[uuid.UUID], principal: Principal
    ) -> frozenset[uuid.UUID]:
        """Return the ids of ``ids`` whose Event the caller reads."""
        teams = await self.teams(principal)
        if not ids or not teams:
            return frozenset()
        rows = await self.session.scalars(
            select(Event.id).where(Event.id.in_(list(ids)), Event.team_id.in_(list(teams)))
        )
        return frozenset(rows.all())
