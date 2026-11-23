"""arq task of the Paperless integration: the filing cron.

``process_paperless_filings`` runs every minute. Without a connection and while the
feature `paperless` is off (§F/integrations/paperless/002762) it does nothing.
It opens a job for each new file (`new_filings`), runs each due job in its own
transaction, so one broken file does not undo the others, and gives the tag `Ersetzt` to
the replaced documents. A job of a part whose switch is off waits
(§F/integrations/paperless/002512). An error of the run itself logs and does not stop
the run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.paperless.client import PaperlessClient
from app.modules.paperless.connection import ClientFactory, ConnectionService, default_client
from app.modules.paperless.filings import due_filings, open_filings
from app.modules.paperless.models import PaperlessSettings
from app.modules.paperless_filing.files import FileBuilder
from app.modules.paperless_filing.runner import FilingRunner
from app.modules.paperless_filing.sources import new_filings, open_kinds
from app.modules.site_config.features import Feature
from app.settings import Settings
from worker.features import job_feature_on

logger = logging.getLogger("worker.paperless")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via ``ctx['paperless_sessionmaker']``)."""
    maker = ctx.get("paperless_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _client_factory(ctx: dict[str, Any]) -> ClientFactory:
    """Return the client factory (tests inject one via ``ctx['paperless_client_factory']``)."""
    factory = ctx.get("paperless_client_factory")
    return factory if factory is not None else default_client


def _runner(ctx: dict[str, Any], session: AsyncSession, client: PaperlessClient) -> FilingRunner:
    settings: Settings = ctx["settings"]
    builder = FileBuilder(
        session,
        storage=ctx.get("object_storage"),
        typst=ctx.get("typst_client"),
        settings=settings,
    )
    return FilingRunner(session=session, client=client, builder=builder)


async def _open(
    ctx: dict[str, Any], maker: async_sessionmaker[AsyncSession]
) -> tuple[PaperlessSettings, PaperlessClient | None]:
    """Open the jobs of the new files; return the settings and the client."""
    settings: Settings = ctx["settings"]
    async with maker() as session:
        connection = ConnectionService(session, settings, _client_factory(ctx))
        row = await connection.row()
        client = await connection.client()
        if client is not None:
            await open_filings(session, await new_filings(session, row))
        await session.commit()
        return row, client


async def _run_one(
    ctx: dict[str, Any],
    maker: async_sessionmaker[AsyncSession],
    client: PaperlessClient,
    filing_id: UUID,
    moment: datetime,
) -> bool:
    """Run one job in its own transaction; return whether it filed its document."""
    try:
        async with maker() as session:
            outcome = await _runner(ctx, session, client).run(filing_id, moment)
            await session.commit()
            return outcome == "filed"
    except Exception:
        logger.exception("paperless filing crashed (filing=%s)", filing_id)
        return False


async def process_paperless_filings(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Open the jobs of the new files and run each due job.

    Returns:
        The number of documents that this run filed.
    """
    moment = now or datetime.now(UTC)
    maker = _sessionmaker(ctx)
    if not await job_feature_on(maker, Feature.PAPERLESS):
        return 0
    row, client = await _open(ctx, maker)
    if client is None:
        return 0
    async with maker() as session:
        due = await due_filings(session, moment, open_kinds(row))
    filed = sum([await _run_one(ctx, maker, client, filing_id, moment) for filing_id in due])
    async with maker() as session:
        await _runner(ctx, session, client).tag_replaced(moment)
        await session.commit()
    return filed
