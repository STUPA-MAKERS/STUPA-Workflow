"""arq pool lifecycle and mail-queue provisioning.

The API never sends mail itself; it enqueues jobs in Redis (arq) for the worker.
The pool is opened best-effort at startup: if Redis is missing the pool stays
``None`` and the mail queue stays ``None``, so callers log and skip (no crash).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.modules.notifications.queue import ArqMailQueue, MailQueue

if TYPE_CHECKING:
    from arq.connections import ArqRedis

logger = logging.getLogger("app.mail")

_POOL_OPEN_TIMEOUT = 5.0


async def create_mail_pool(redis_url: str) -> ArqRedis | None:
    """Open the arq pool best-effort; return None on error/timeout."""
    from arq import create_pool
    from arq.connections import RedisSettings

    try:
        return await asyncio.wait_for(
            create_pool(RedisSettings.from_dsn(redis_url)),
            timeout=_POOL_OPEN_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 - never block startup (Redis optional)
        logger.warning("mail pool unavailable (%s): %s", type(exc).__name__, exc)
        return None


async def close_mail_pool(pool: ArqRedis | None) -> None:
    """Close the pool on shutdown."""
    if pool is not None:
        await pool.aclose()


def mail_queue_from_pool(pool: ArqRedis | None) -> MailQueue | None:
    """Wrap the pool in a MailQueue, or None when there is no pool."""
    return ArqMailQueue(pool) if pool is not None else None
