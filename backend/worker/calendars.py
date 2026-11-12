"""arq task of the external calendars: the fetch cron.

``fetch_external_calendars`` runs every minute. It fetches each external calendar whose
``due_at`` is over (`ExternalCalendarService.due`), at most `BATCH` per run, one after
the other and each in its own transaction, so one slow or broken feed does not undo the
others. A fetch goes through the SSRF guard and stops at 2 MB or 10 seconds
(`HttpFeedFetcher`). A failed fetch keeps the entries of the last good one. An error of
the run itself logs and does not stop the run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.calendar.external import ExternalCalendarService
from app.modules.calendar.external_fetch import FeedFetcher, HttpFeedFetcher
from app.modules.site_config.features import Feature
from worker.features import job_feature_on

logger = logging.getLogger("worker.calendars")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['calendars_sessionmaker']``)."""
    maker = ctx.get("calendars_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _fetcher(ctx: dict[str, Any]) -> FeedFetcher:
    """Return the feed fetcher (tests inject one via ``ctx['calendars_fetcher']``)."""
    fetcher = ctx.get("calendars_fetcher")
    return fetcher if fetcher is not None else HttpFeedFetcher()


async def _fetch_one(
    maker: async_sessionmaker[AsyncSession],
    fetcher: FeedFetcher,
    calendar_id: UUID,
    moment: datetime,
) -> bool:
    """Fetch one calendar in its own transaction; return whether the fetch was good."""
    try:
        async with maker() as session:
            good = await ExternalCalendarService(session).refresh(calendar_id, fetcher, moment)
            await session.commit()
            return good
    except Exception:
        logger.exception("external calendar fetch crashed (calendar=%s)", calendar_id)
        return False


async def fetch_external_calendars(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Fetch every due external calendar.

    Returns:
        The number of good fetches. None while `Kalender` is off.
    """
    moment = now or datetime.now(UTC)
    maker = _sessionmaker(ctx)
    if not await job_feature_on(maker, Feature.CALENDAR):
        return 0
    fetcher = _fetcher(ctx)
    async with maker() as session:
        due = await ExternalCalendarService(session).due(moment)
    return sum([await _fetch_one(maker, fetcher, calendar_id, moment) for calendar_id in due])
