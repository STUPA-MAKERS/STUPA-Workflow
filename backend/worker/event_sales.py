"""arq tasks of the pretix and Mollie integrations: the reads and the bookings.

``read_pretix_sales`` runs every 15 minutes and reads the sales of each active linked
pretix event and books its new orders (§F/integrations/pretix/003085, 003086).
``read_mollie_money`` runs every hour and reads and books the Mollie data
(§F/integrations/mollie/003094, 003097, 003103). Both run in one transaction under the lock
of `event_sales.sync`: while a run holds it, the job does nothing, because the other run
reads the same data. A run reads only the integrations that are on and configured.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.event_sales.sync import Factories, PretixScope, run
from app.settings import Settings
from app.shared.errors import ConflictError

logger = logging.getLogger("worker.event_sales")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['sales_sessionmaker']``)."""
    maker = ctx.get("sales_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _factories(ctx: dict[str, Any]) -> Factories:
    """Return the client factories (tests inject fakes via ``ctx['sales_factories']``)."""
    found = ctx.get("sales_factories")
    return found if isinstance(found, Factories) else Factories()


async def _run(
    ctx: dict[str, Any], now: datetime | None, *, pretix: PretixScope, mollie: bool
) -> int:
    settings: Settings = ctx["settings"]
    moment = now or datetime.now(UTC)
    today = moment.astimezone(ZoneInfo(settings.local_timezone)).date()
    async with _sessionmaker(ctx)() as session:
        try:
            outcome = await run(
                session,
                settings,
                now=moment,
                today=today,
                pretix=pretix,
                mollie=mollie,
                factories=_factories(ctx),
            )
        except ConflictError:
            logger.info("event sales run skipped: another run holds the lock")
            return 0
        await session.commit()
    for failure in outcome.failures:
        logger.warning(
            "event sales %s %s %s failed: %s",
            failure.integration,
            failure.source,
            failure.key,
            failure.cause,
        )
    return outcome.booked


async def read_pretix_sales(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Read the sales of the active linked pretix events and book their orders.

    Returns:
        The number of new bookings.
    """
    return await _run(ctx, now, pretix="active", mollie=False)


async def read_mollie_money(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Read the Mollie payments, refunds, chargebacks and settlements and book them.

    Returns:
        The number of new bookings.
    """
    return await _run(ctx, now, pretix=None, mollie=True)
