"""arq pool lifecycle and mail-queue provisioning.

The API never sends a mail itself. It puts the jobs into Redis (arq) for the
worker. The startup opens the pool best effort. If Redis is missing, the pool
stays `None` and the mail queue stays `None`. The callers then log and skip the
mail instead of crashing.
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
    """Open the arq pool best effort.

    Returns:
        The pool, or None after an error or a timeout.
    """
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
    """Wrap the pool in a `MailQueue`, or return None when there is no pool."""
    return ArqMailQueue(pool) if pool is not None else None
