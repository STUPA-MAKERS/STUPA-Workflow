"""Routes of the Veranstaltungen (F/collaboration/events/003027).

Every route needs a session. The rights come from the team of the Event (003026): a
member of the team reads and writes it, and every other person gets 404. The feature
switch ``events`` closes every route under ``/events`` (003032, ``feature_gate``).

- ``GET /events`` lists the Events of the teams of the caller, by segment, team, series
  and search (003028).
- ``GET /events/teams`` lists the teams of the caller, ``GET /events/refs`` the Events of
  the picker of a Buchung (003033), ``GET``/``POST /events/series`` the series (000483).
- ``GET /events/export.xlsx`` gives the list of the filter as a file and needs
  ``finance.export`` (003034).
- ``POST /events``, ``GET``/``PATCH``/``DELETE /events/{id}`` and
  ``POST /events/{id}/status`` read and write one Event.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response, status

from app.deps import DbSession, SettingsDep, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.budget.access import EXPORT_PERMISSION
from app.modules.events.listing import EventFilter, EventListing
from app.modules.events.rules import Segment
from app.modules.events.schemas import (
    EventCreate,
    EventDetailOut,
    EventOut,
    EventRefOut,
    EventStatusIn,
    EventTeamOut,
    EventUpdate,
    SeriesCreate,
    SeriesOut,
)
from app.modules.events.service import EventService
from app.modules.statuses.service import StatusReader
from app.shared.paging import Page, PageParams

router = APIRouter(tags=["events"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"description": "problem+json"} for code in (401, 403, 404, 409, 422)
}
#: The most rows of one export.
EXPORT_MAX_ROWS = 10_000
_HEADERS: tuple[str, ...] = (
    "Nummer",
    "Name",
    "Status",
    "Team",
    "Reihe",
    "Beginn",
    "Beginn Uhrzeit",
    "Ende",
    "Ende Uhrzeit",
    "Ort",
    "Teilnehmende",
    "Shop",
    "Beantragt",
    "Bewilligt",
    "Ausgaben",
    "Einnahmen",
    "Saldo",
)
#: The places of the amount columns in `_HEADERS`.
_MONEY_COLUMNS = frozenset({12, 13, 14, 15, 16})

Member = Annotated[Principal, Depends(require_principal())]
ExporterDep = Annotated[Principal, Depends(require_principal(EXPORT_PERMISSION))]


def get_event_service(db: DbSession, settings: SettingsDep) -> EventService:
    """Build the service with the current day in the local time zone."""
    return EventService(db, today=datetime.now(ZoneInfo(settings.local_timezone)).date())


ServiceDep = Annotated[EventService, Depends(get_event_service)]


def _wanted(
    segment: Annotated[Segment | None, Query()] = None,
    team_id: Annotated[UUID | None, Query(alias="team")] = None,
    series_id: Annotated[UUID | None, Query(alias="series")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> EventFilter:
    """Read the filter of the page from the query (003028)."""
    return EventFilter(segment=segment, team_id=team_id, series_id=series_id, q=q)


FilterDep = Annotated[EventFilter, Depends(_wanted)]


@router.get("/events", response_model=Page[EventOut], responses=_ERRORS)
async def list_events(
    db: DbSession,
    service: ServiceDep,
    principal: Member,
    wanted: FilterDep,
    page: Annotated[PageParams, Depends()],
) -> Page[EventOut]:
    """List the Events of the teams of the caller.

    ``segment`` is ``upcoming``, ``past``, ``done`` or ``void`` (003028).
    """
    rows, total = await EventListing(db, service.today).page(
        await service.teams(principal), wanted, limit=page.limit, offset=page.offset
    )
    return Page(items=await service.views(rows), total=total, limit=page.limit, offset=page.offset)


@router.get("/events/teams", response_model=list[EventTeamOut], responses=_ERRORS)
async def list_event_teams(service: ServiceDep, principal: Member) -> list[EventTeamOut]:
    """List the teams of the caller: the teams of a new Event and of the chip Team."""
    return await service.team_options(principal)


@router.get("/events/refs", response_model=list[EventRefOut], responses=_ERRORS)
async def list_event_refs(
    service: ServiceDep,
    principal: Member,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[EventRefOut]:
    """List the open Events that the caller writes: the picker of a Buchung (003033)."""
    return await service.refs(q, principal)


@router.get("/events/series", response_model=list[SeriesOut], responses=_ERRORS)
async def list_series(
    service: ServiceDep,
    _principal: Member,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[SeriesOut]:
    """List the series by name (at most 50)."""
    return await service.series(q)


@router.post(
    "/events/series",
    response_model=SeriesOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_series(
    db: DbSession, service: ServiceDep, principal: Member, payload: SeriesCreate
) -> SeriesOut:
    """Create a series; the name is unique, case ignored (409 ``series_exists``)."""
    out = await service.create_series(payload.name, principal)
    await db.commit()
    return out


@router.get("/events/export.xlsx", responses=_ERRORS)
async def export_events_xlsx(
    db: DbSession, service: ServiceDep, principal: ExporterDep, wanted: FilterDep
) -> Response:
    """Export the Events of the filter that the caller reads as ``.xlsx`` (003034)."""
    from app.shared.xlsx import XLSX_MEDIA_TYPE, build_table_workbook

    rows, _ = await EventListing(db, service.today).page(
        await service.teams(principal), wanted, limit=EXPORT_MAX_ROWS, offset=0
    )
    names = {
        row.key: str(row.name.get("de") or row.key) for row in await StatusReader(db).rows("event")
    }
    data = build_table_workbook(
        title="Veranstaltungen",
        head=(),
        headers=_HEADERS,
        rows=[
            (
                item.number,
                item.title,
                names.get(item.status, item.status),
                item.team_name or "",
                item.series_name or "",
                item.starts_on.isoformat() if item.starts_on else "",
                item.start_time.strftime("%H:%M") if item.start_time else "",
                item.ends_on.isoformat() if item.ends_on else "",
                item.end_time.strftime("%H:%M") if item.end_time else "",
                item.place or "",
                item.participants if item.participants is not None else "",
                item.shop_url or "",
                Decimal(item.totals.requested),
                Decimal(item.totals.approved),
                Decimal(item.totals.expenses),
                Decimal(item.totals.income),
                Decimal(item.totals.balance),
            )
            for item in await service.views(rows)
        ],
        money_columns=_MONEY_COLUMNS,
    )
    await audit_record(
        db,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="veranstaltungen.xlsx",
        data={"rows": len(rows)},
    )
    await db.commit()
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="veranstaltungen.xlsx"'},
    )


@router.post(
    "/events",
    response_model=EventDetailOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_event(
    db: DbSession, service: ServiceDep, principal: Member, payload: EventCreate
) -> EventDetailOut:
    """Create an Event in a team of the caller with the start status of the list."""
    row = await service.create(payload, principal)
    out = await service.detail(row, principal)
    await db.commit()
    return out


@router.get("/events/{event_id}", response_model=EventDetailOut, responses=_ERRORS)
async def get_event(event_id: UUID, service: ServiceDep, principal: Member) -> EventDetailOut:
    """Read one Event with its totals, decisions and series (003029)."""
    return await service.detail(await service.get(event_id, principal), principal)


@router.patch("/events/{event_id}", response_model=EventDetailOut, responses=_ERRORS)
async def update_event(
    event_id: UUID, db: DbSession, service: ServiceDep, principal: Member, payload: EventUpdate
) -> EventDetailOut:
    """Change the fields that the body names; a stale version gets 409."""
    row = await service.update(event_id, payload, principal)
    out = await service.detail(row, principal)
    await db.commit()
    return out


@router.post("/events/{event_id}/status", response_model=EventDetailOut, responses=_ERRORS)
async def set_event_status(
    event_id: UUID, db: DbSession, service: ServiceDep, principal: Member, payload: EventStatusIn
) -> EventDetailOut:
    """Set a status of the list of the Events (003025)."""
    row = await service.set_status(event_id, payload.status, payload.version, principal)
    out = await service.detail(row, principal)
    await db.commit()
    return out


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
async def delete_event(
    event_id: UUID, db: DbSession, service: ServiceDep, principal: Member
) -> Response:
    """Delete an Event; its links go with it."""
    await service.delete(event_id, principal)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
