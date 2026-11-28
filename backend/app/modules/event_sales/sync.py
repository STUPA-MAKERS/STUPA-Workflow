"""One run of the pretix and Mollie reads and bookings, under one lock.

The worker crons, the action `Daten abrufen` (§F/integrations/mollie/003104) and the action
`Aktualisieren` of an Event (§F/integrations/pretix/003085) all run here. A run holds a
transaction-level advisory lock of Postgres, so a second run during a run gets 409
`sync_running` and the lock ends with the transaction, also after a crash. A run reads only
the integrations whose feature is on, together with the feature `events`, and whose
connection is complete (003081, 003093).

No function here commits. The worker and the router own the transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.event_sales.mollie_sync import book_mollie, read_mollie
from app.modules.event_sales.outcome import Outcome
from app.modules.event_sales.pretix_sync import active_links, sync_links
from app.modules.mollie import connection as mollie_connection
from app.modules.pretix import connection as pretix_connection
from app.modules.pretix.models import PretixEventLink
from app.modules.site_config.features import Feature, active_features
from app.settings import Settings
from app.shared.errors import ConflictError

#: The key of the advisory lock of a run.
LOCK_KEY = 0x5052_4554_4958

#: Which pretix events a run reads: the active ones, one Event, or none.
PretixScope = Literal["active"] | uuid.UUID | None


@dataclass(frozen=True, slots=True)
class Factories:
    """The client factories of both integrations; a test injects fakes."""

    pretix: pretix_connection.ClientFactory = pretix_connection.default_client
    mollie: mollie_connection.ClientFactory = mollie_connection.default_client


@dataclass(frozen=True, slots=True)
class Available:
    """Which integrations a run reads: feature on and connection complete (003104)."""

    pretix: bool
    mollie: bool


async def available(session: AsyncSession, settings: Settings) -> Available:
    """Tell which integrations are on and configured."""
    features = await active_features(session)
    events = Feature.EVENTS in features
    pretix_row = await pretix_connection.ConnectionService(session, settings).row()
    mollie_row = await mollie_connection.ConnectionService(session).row()
    return Available(
        pretix=events and Feature.PRETIX in features and pretix_connection.connected(pretix_row),
        mollie=events and Feature.MOLLIE in features and mollie_connection.connected(mollie_row),
    )


async def try_lock(session: AsyncSession) -> bool:
    """Take the lock of a run for the running transaction; False while another run holds it."""
    return bool(await session.scalar(select(func.pg_try_advisory_xact_lock(LOCK_KEY))))


async def _pretix(
    session: AsyncSession,
    settings: Settings,
    factories: Factories,
    scope: PretixScope,
    now: datetime,
    today: date,
) -> Outcome:
    service = pretix_connection.ConnectionService(session, settings, factories.pretix)
    row = await service.row()
    client = await service.client()
    if client is None or scope is None:
        return Outcome()
    links = (
        await active_links(session, today)
        if scope == "active"
        else (
            await session.scalars(select(PretixEventLink).where(PretixEventLink.event_id == scope))
        ).all()
    )
    return await sync_links(session, client, row, links, now)


async def _mollie(
    session: AsyncSession, settings: Settings, factories: Factories, now: datetime
) -> Outcome:
    service = mollie_connection.ConnectionService(session, factories.mollie)
    client = await service.client()
    if client is None:
        return Outcome()
    read = await read_mollie(session, client, now)
    row = await service.row()
    pretix = await pretix_connection.ConnectionService(session, settings).row()
    return read + await book_mollie(session, row, pretix)


async def run(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime,
    today: date,
    pretix: PretixScope,
    mollie: bool,
    factories: Factories | None = None,
) -> Outcome:
    """Run the reads and the bookings of the integrations that are on.

    Raises:
        ConflictError: Another run holds the lock (409 `sync_running`).
    """
    if not await try_lock(session):
        raise ConflictError("A run is in progress.", code="sync_running")
    clients = factories or Factories()
    on = await available(session, settings)
    first = (
        await _pretix(session, settings, clients, pretix, now, today) if on.pretix else Outcome()
    )
    second = await _mollie(session, settings, clients, now) if on.mollie and mollie else Outcome()
    return first + second
