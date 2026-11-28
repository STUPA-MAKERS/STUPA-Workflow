"""The routes of the pretix and Mollie integrations.

- `/admin/pretix` (`admin.pretix`) and `/admin/mollie` (`admin.mollie`): the connection,
  the test and the bookings that failed (§F/integrations/pretix/003080,
  §F/integrations/mollie/003092).
- `/pretix/events` lists the events of the organizer for the picker, and
  `/pretix/links/{event_id}` sets and removes the link of an Event (003083): `pretix.use`
  and the write right of the Event (003091). `/pretix/links/{event_id}/income-budget` sets
  the field `Einnahmen-Kostenstelle`: `budget.book` and the write right (003086).
- `/events/{event_id}/sales` reads the section `Verkauf` with the read right of the Event,
  `/events/{event_id}/sales/refresh` is the action `Aktualisieren` (003085).
- `/sales-sync` tells which integrations the action `Daten abrufen` reads and runs it
  (003104).

The feature switches `pretix` and `mollie` close their routes (`feature_routes.py`); the
routes under `/events` follow the switch `events`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.deps import DbSession, Principal, SettingsDep, refuse_agent_token, require_principal
from app.modules.event_sales import links, mollie_sync, pretix_sync
from app.modules.event_sales.outcome import Outcome
from app.modules.event_sales.sales import (
    BUDGET_BOOK,
    PRETIX_USE,
    SalesContext,
    event_sales,
    link_out,
)
from app.modules.event_sales.schemas import (
    EventSalesOut,
    FailedBookingsOut,
    SyncFailureOut,
    SyncResultOut,
    SyncStateOut,
)
from app.modules.event_sales.sync import Factories, available, run
from app.modules.events.service import EventService
from app.modules.mollie import connection as mollie_connection
from app.modules.mollie.schemas import ConnectionIn as MollieIn
from app.modules.mollie.schemas import ConnectionOut as MollieOut
from app.modules.mollie.schemas import ConnectionTestOut as MollieTestOut
from app.modules.pretix import connection as pretix_connection
from app.modules.pretix.client import PretixError
from app.modules.pretix.models import PretixEventLink
from app.modules.pretix.schemas import ConnectionIn as PretixIn
from app.modules.pretix.schemas import ConnectionOut as PretixOut
from app.modules.pretix.schemas import ConnectionTestOut as PretixTestOut
from app.modules.pretix.schemas import (
    FailedBookingOut,
    IncomeBudgetIn,
    LinkIn,
    LinkOut,
    PretixEventOut,
)
from app.modules.site_config.features import Feature, FeatureDisabledError, active_features
from app.shared.errors import (
    ForbiddenError,
    NotFoundError,
    ProblemDetail,
    RateLimitedError,
    ServiceUnavailableError,
)

pretix_admin_router = APIRouter(prefix="/admin/pretix", tags=["pretix"])
mollie_admin_router = APIRouter(prefix="/admin/mollie", tags=["mollie"])
pretix_router = APIRouter(prefix="/pretix", tags=["pretix"])
router = APIRouter(tags=["events"])

__all__ = [
    "get_factories",
    "mollie_admin_router",
    "pretix_admin_router",
    "pretix_router",
    "router",
]

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_ERRORS: dict[int | str, dict[str, Any]] = dict.fromkeys(
    (401, 403, 404, 409, 422, 429, 503), _PROBLEM
)

PretixAdmin = Annotated[Principal, Depends(require_principal("admin.pretix"))]
MollieAdmin = Annotated[Principal, Depends(require_principal("admin.mollie"))]
PretixUser = Annotated[Principal, Depends(require_principal(PRETIX_USE))]
Booker = Annotated[Principal, Depends(require_principal(BUDGET_BOOK))]
Member = Annotated[Principal, Depends(require_principal())]

#: The shortest time between two reads of the action `Aktualisieren` of one Event (003085).
REFRESH_EVERY = timedelta(minutes=1)


def get_factories() -> Factories:
    """Return the client factories; a test overrides this dependency with fakes."""
    return Factories()


FactoriesDep = Annotated[Factories, Depends(get_factories)]


def _today(settings: SettingsDep) -> date:
    return datetime.now(ZoneInfo(settings.local_timezone)).date()


def _events(db: DbSession, settings: SettingsDep) -> EventService:
    return EventService(db, today=_today(settings))


EventsDep = Annotated[EventService, Depends(_events)]


def _failed(rows: list[FailedBookingOut]) -> FailedBookingsOut:
    return FailedBookingsOut(items=tuple(rows))


def _result(outcome: Outcome) -> SyncResultOut:
    return SyncResultOut(
        booked=outcome.booked,
        failures=tuple(
            SyncFailureOut(
                integration=item.integration, source=item.source, key=item.key, cause=item.cause
            )
            for item in outcome.failures
        ),
    )


@pretix_admin_router.get("", responses=_ERRORS)
async def read_pretix_connection(
    _admin: PretixAdmin, db: DbSession, settings: SettingsDep
) -> PretixOut:
    """Read the pretix connection and its switches, without the token."""
    out = await pretix_connection.ConnectionService(db, settings).read()
    await db.commit()
    return out


@pretix_admin_router.put("", responses=_ERRORS)
async def save_pretix_connection(
    data: PretixIn, admin: PretixAdmin, db: DbSession, settings: SettingsDep
) -> PretixOut:
    """Save the pretix connection and its switches (422 `pretix_host_not_allowed`)."""
    out = await pretix_connection.ConnectionService(db, settings).save(data, actor=admin.sub)
    await db.commit()
    return out


@pretix_admin_router.post("/test", responses=_ERRORS)
async def test_pretix_connection(
    admin: PretixAdmin, db: DbSession, settings: SettingsDep, factories: FactoriesDep
) -> PretixTestOut:
    """Call pretix with the stored connection and tell the result."""
    refuse_agent_token(admin, "An agent token cannot call pretix.")
    out = await pretix_connection.ConnectionService(db, settings, factories.pretix).test()
    await db.commit()
    return out


@pretix_admin_router.get("/failed-bookings", responses=_ERRORS)
async def list_pretix_failed(_admin: PretixAdmin, db: DbSession) -> FailedBookingsOut:
    """List the bookings of orders that the platform could not make, with their cause."""
    rows = await pretix_sync.failed_bookings(db)
    return _failed(
        [
            FailedBookingOut(
                source=row.source, key=row.source_key, error=row.error or "", at=row.updated_at
            )
            for row in rows
        ]
    )


@mollie_admin_router.get("", responses=_ERRORS)
async def read_mollie_connection(_admin: MollieAdmin, db: DbSession) -> MollieOut:
    """Read the Mollie connection and its fields, without the token."""
    out = await mollie_connection.ConnectionService(db).read()
    await db.commit()
    return out


@mollie_admin_router.put("", responses=_ERRORS)
async def save_mollie_connection(data: MollieIn, admin: MollieAdmin, db: DbSession) -> MollieOut:
    """Save the Mollie token and the cost centres of the bookings."""
    out = await mollie_connection.ConnectionService(db).save(data, actor=admin.sub)
    await db.commit()
    return out


@mollie_admin_router.post("/test", responses=_ERRORS)
async def test_mollie_connection(
    admin: MollieAdmin, db: DbSession, factories: FactoriesDep
) -> MollieTestOut:
    """Call Mollie with the stored token and tell the result and the organization."""
    refuse_agent_token(admin, "An agent token cannot call Mollie.")
    out = await mollie_connection.ConnectionService(db, factories.mollie).test()
    await db.commit()
    return out


@mollie_admin_router.get("/failed-bookings", responses=_ERRORS)
async def list_mollie_failed(_admin: MollieAdmin, db: DbSession) -> FailedBookingsOut:
    """List the Mollie bookings that the platform could not make, with their cause."""
    rows = await mollie_sync.failed_bookings(db)
    return _failed(
        [
            FailedBookingOut(
                source=row.source, key=row.source_id, error=row.error or "", at=row.updated_at
            )
            for row in rows
        ]
    )


@pretix_router.get("/events", responses=_ERRORS)
async def list_pretix_events(
    user: PretixUser, db: DbSession, settings: SettingsDep, factories: FactoriesDep
) -> list[PretixEventOut]:
    """List the events of the organizer for the picker `Pretix-Veranstaltung` (003083).

    Raises:
        NotFoundError: The connection is incomplete.
        ServiceUnavailableError: pretix does not answer (503 `pretix_unavailable`).
    """
    refuse_agent_token(user, "An agent token cannot call pretix.")
    client = await pretix_connection.ConnectionService(db, settings, factories.pretix).client()
    if client is None:
        raise NotFoundError("pretix is not connected.", code="pretix_off")
    try:
        events = await client.events()
    except PretixError as exc:
        raise ServiceUnavailableError("pretix does not answer.", code="pretix_unavailable") from exc
    taken = frozenset((await db.scalars(select(PretixEventLink.slug))).all())
    return [
        PretixEventOut(
            slug=item.slug, name=item.name, date_from=item.date_from, taken=item.slug in taken
        )
        for item in events
    ]


@pretix_router.put("/links/{event_id}", responses=_ERRORS)
async def set_pretix_link(
    event_id: uuid.UUID,
    data: LinkIn,
    user: PretixUser,
    db: DbSession,
    settings: SettingsDep,
    events: EventsDep,
    factories: FactoriesDep,
) -> LinkOut:
    """Link an Event to a pretix event (003083).

    Without a shop the Event gets the public address of the pretix event.

    Raises:
        NotFoundError: The caller does not write the Event, or pretix has no such event.
        ConflictError: Another Event links it (409 `pretix_event_taken`).
        ServiceUnavailableError: pretix does not answer (503 `pretix_unavailable`).
    """
    refuse_agent_token(user, "Only a person links a pretix event.")
    event = await events.get(event_id, user)
    client = await pretix_connection.ConnectionService(db, settings, factories.pretix).client()
    if client is None:
        raise NotFoundError("pretix is not connected.", code="pretix_off")
    await links.check_free(db, event_id, data.slug)
    try:
        found = await client.event(data.slug)
    except PretixError as exc:
        if exc.code == "not_found":
            raise NotFoundError("pretix has no such event.", code="pretix_event_unknown") from exc
        raise ServiceUnavailableError("pretix does not answer.", code="pretix_unavailable") from exc
    await links.check_free(db, event_id, found.slug)
    out = await link_out(db, await links.set_link(db, event, found, user.sub))
    await db.commit()
    return out


@pretix_router.delete(
    "/links/{event_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS
)
async def remove_pretix_link(
    event_id: uuid.UUID, user: PretixUser, db: DbSession, events: EventsDep
) -> Response:
    """Remove the link of an Event to its pretix event (003083)."""
    refuse_agent_token(user, "Only a person links a pretix event.")
    await events.get(event_id, user)
    await links.remove_link(db, event_id, user.sub)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@pretix_router.put("/links/{event_id}/income-budget", responses=_ERRORS)
async def set_income_budget(
    event_id: uuid.UUID, data: IncomeBudgetIn, user: Booker, db: DbSession, events: EventsDep
) -> LinkOut:
    """Set the field `Einnahmen-Kostenstelle` of a linked Event (003086)."""
    refuse_agent_token(user, "Only a person links a pretix event.")
    await events.get(event_id, user)
    out = await link_out(db, await links.set_income_budget(db, event_id, data.budget_id, user.sub))
    await db.commit()
    return out


async def _context(db: DbSession, settings: SettingsDep) -> SalesContext:
    features = await active_features(db)
    return SalesContext(
        pretix=await pretix_connection.ConnectionService(db, settings).row(),
        mollie=await mollie_connection.ConnectionService(db).row(),
        pretix_on=Feature.PRETIX in features,
        mollie_on=Feature.MOLLIE in features,
    )


@router.get("/events/{event_id}/sales", responses=_ERRORS)
async def read_event_sales(
    event_id: uuid.UUID,
    principal: Member,
    db: DbSession,
    settings: SettingsDep,
    events: EventsDep,
) -> EventSalesOut:
    """Read the section `Verkauf` of an Event (003084, 003096)."""
    await events.get(event_id, principal)
    out = await event_sales(db, event_id, principal, await _context(db, settings))
    await db.commit()
    return out


@router.post("/events/{event_id}/sales/refresh", responses=_ERRORS)
async def refresh_event_sales(
    event_id: uuid.UUID,
    principal: Member,
    db: DbSession,
    settings: SettingsDep,
    events: EventsDep,
    factories: FactoriesDep,
) -> SyncResultOut:
    """Read the pretix sales and the Mollie payments of one Event now (003085, 003104).

    Raises:
        RateLimitedError: The newest read of this Event is less than a minute old (429
            `refresh_too_soon`).
        ConflictError: Another run is in progress (409 `sync_running`).
    """
    refuse_agent_token(principal, "An agent token cannot call pretix or Mollie.")
    await events.get(event_id, principal)
    now = datetime.now(UTC)
    link = await links.link_of(db, event_id)
    if (
        link is not None
        and link.refreshed_at is not None
        and now - link.refreshed_at < REFRESH_EVERY
    ):
        wait = REFRESH_EVERY - (now - link.refreshed_at)
        raise RateLimitedError(
            "The sales were read less than a minute ago.",
            code="refresh_too_soon",
            retry_after=int(wait.total_seconds()) + 1,
        )
    await links.mark_refreshed(db, link, now)
    outcome = await run(
        db,
        settings,
        now=now,
        today=_today(settings),
        pretix=event_id,
        mollie=True,
        factories=factories,
    )
    await db.commit()
    return _result(outcome)


@router.get("/sales-sync", responses=_ERRORS)
async def read_sync_state(_principal: Member, db: DbSession, settings: SettingsDep) -> SyncStateOut:
    """Tell which integrations the action `Daten abrufen` reads (003104)."""
    on = await available(db, settings)
    await db.commit()
    return SyncStateOut(pretix=on.pretix, mollie=on.mollie)


@router.post("/sales-sync", responses=_ERRORS)
async def run_sync(
    principal: Member,
    db: DbSession,
    settings: SettingsDep,
    events: EventsDep,
    factories: FactoriesDep,
    page: Annotated[Literal["bookings", "events"], Query()],
) -> SyncResultOut:
    """Run the action `Daten abrufen` of the page `Buchungen` or `Veranstaltungen` (003104).

    Raises:
        ForbiddenError: The page `Buchungen` without `budget.book`, or the page
            `Veranstaltungen` without the write right of an Event.
        FeatureDisabledError: No integration is on and configured.
        ConflictError: Another run is in progress (409 `sync_running`).
    """
    refuse_agent_token(principal, "An agent token cannot call pretix or Mollie.")
    allowed = (
        principal.has(BUDGET_BOOK) if page == "bookings" else bool(await events.teams(principal))
    )
    if not allowed:
        raise ForbiddenError("The action needs the right of its page.", code="sync_forbidden")
    on = await available(db, settings)
    if not on.pretix and not on.mollie:
        raise FeatureDisabledError(frozenset({Feature.PRETIX, Feature.MOLLIE}))
    outcome = await run(
        db,
        settings,
        now=datetime.now(UTC),
        today=_today(settings),
        pretix="active",
        mollie=True,
        factories=factories,
    )
    await db.commit()
    return _result(outcome)
