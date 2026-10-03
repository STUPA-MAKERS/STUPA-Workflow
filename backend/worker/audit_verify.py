"""arq worker tasks: the stored audit-chain check (Z6/O8).

`process_audit_verification` is the nightly cron at 04:30. It does not depend on the
backup: it runs also when backups are off or when the backup failed. `verify_after_restore`
runs the same check in the restored database, with ``trigger = restore``.

Both tasks call `AuditService.verify_and_store`. That method stores the result, keeps
the newest 100 rows and logs the duration.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.audit.models import VerificationTrigger
from app.modules.audit.service import AuditService

logger = logging.getLogger("worker.audit_verify")


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """Return the DB sessionmaker (tests inject one via `ctx['audit_sessionmaker']`)."""
    maker = ctx.get("audit_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


async def run_verification(
    maker: async_sessionmaker[AsyncSession],
    *,
    trigger: VerificationTrigger,
    triggered_by: str | None = None,
) -> str:
    """Verify the chain in a new session and store the result.

    Returns:
        A short summary for the arq log, for example ``valid checked=42``.
    """
    async with maker() as session:
        row = await AuditService(session).verify_and_store(
            trigger=trigger, triggered_by=triggered_by
        )
    if row.valid:
        return f"valid checked={row.checked}"
    return f"broken checked={row.checked} broken_at={row.broken_at} reason={row.reason}"


async def process_audit_verification(ctx: dict[str, Any]) -> str:
    """Nightly cron entry point: verify the chain with ``trigger = cron``."""
    return await run_verification(_sessionmaker(ctx), trigger="cron")


async def verify_after_restore(
    maker: async_sessionmaker[AsyncSession], actor: str | None
) -> str | None:
    """Verify the restored chain with ``trigger = restore``.

    A failure here must not turn a finished restore into a failed one. The data is
    already back. The function therefore logs the error and returns ``None``. One
    example is an archive from a schema that has no ``audit_verification`` table.

    Returns:
        The summary of `run_verification`, or ``None`` when the check failed to run.
    """
    try:
        return await run_verification(maker, trigger="restore", triggered_by=actor)
    except Exception:  # noqa: BLE001 - the restore itself is done; only log
        logger.exception("audit chain check after the restore failed")
        return None
