"""arq cron task: anonymize the closed tickets past their retention.

`anonymize_tickets` runs once a day at 03:45. A ticket is due when its `closed_at`
(the entry into done or rejected) is older than `tickets.retentionMonths` of the
active site config and it is not anonymized yet. A null `retentionMonths` turns the
job off. A reopen clears `closed_at`, so a reopened ticket is never due.

The anonymization clears the reporter (account and e-mail) and the context and
removes the attachments with their objects. Title, body, notes and events stay; the
`created` event loses its actor, because that actor is the reporter. Each
ticket commits on its own with an `anonymization` audit entry, so one bad row does
not stop the run, and a second run finds nothing.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.admin.site_config_service import active_branding
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.service import FilesService
from app.modules.files.storage import ObjectStorage, build_object_storage
from app.modules.tickets.models import Ticket
from app.modules.tickets.service import TicketService
from app.settings import load_settings

logger = logging.getLogger("worker.tickets")

_ACTOR = "system:retention"


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['tickets_sessionmaker']`)."""
    maker = ctx.get("tickets_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _storage(ctx: dict[str, Any]) -> ObjectStorage | None:
    """Return the object storage of the worker, or build it from the settings."""
    storage: ObjectStorage | None = ctx.get("object_storage")
    if storage is not None:
        return storage
    settings = ctx.get("settings") or load_settings()
    return build_object_storage(settings)


async def _due(maker: async_sessionmaker[AsyncSession]) -> list[UUID]:
    async with maker() as session:
        months = (await active_branding(session)).tickets.retention_months
        if months is None:
            return []
        cutoff = func.now() - func.make_interval(0, months)
        return list(
            (
                await session.scalars(
                    select(Ticket.id)
                    .where(
                        Ticket.anonymized_at.is_(None),
                        Ticket.closed_at.is_not(None),
                        Ticket.closed_at < cutoff,
                    )
                    .order_by(Ticket.closed_at)
                )
            ).all()
        )


async def anonymize_tickets(ctx: dict[str, Any], now: datetime | None = None) -> int:
    """Anonymize every due ticket.

    Returns:
        The number of anonymized tickets.
    """
    moment = now or datetime.now(UTC)
    maker = _sessionmaker(ctx)
    storage = _storage(ctx)
    done = 0
    for ticket_id in await _due(maker):
        try:
            async with maker() as session:
                ticket = await session.get(Ticket, ticket_id)
                if ticket is None or ticket.anonymized_at is not None:
                    continue
                files = FilesService(session, storage=storage)
                await TicketService(session, files=files).anonymize(ticket, actor=_ACTOR)
                ticket.anonymized_at = moment
                await audit_record(
                    session,
                    actor=_ACTOR,
                    action=AuditAction.ANONYMIZATION,
                    target_type="ticket",
                    target_id=str(ticket_id),
                )
                await session.commit()
                done += 1
        except Exception:  # noqa: BLE001 - one bad row must not stop the run
            logger.exception("ticket anonymization failed for %s", ticket_id)
    if done:
        logger.info("anonymized %d ticket(s)", done)
    return done
