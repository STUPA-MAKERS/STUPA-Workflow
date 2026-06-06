"""arq-Pool-Lifecycle + Mail-Queue-Bereitstellung (T-18).

Die API *sendet* nie selbst — sie legt Jobs in Redis (arq), der Worker versendet.
Der Pool wird beim App-Start **best-effort** geöffnet: fehlt Redis (z. B. im
Contract-CI ohne Redis-Service), bleibt der Pool `None` → die Mail-Queue ist
`None` → Aufrufer loggen + überspringen (kein Start-Crash, kein API-Block).
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
    """arq-Pool öffnen (best-effort). Bei Fehler/Timeout → `None` + Warnung."""
    from arq import create_pool
    from arq.connections import RedisSettings

    try:
        return await asyncio.wait_for(
            create_pool(RedisSettings.from_dsn(redis_url)),
            timeout=_POOL_OPEN_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — Start nie blocken (Redis optional)
        logger.warning("mail pool unavailable (%s): %s", type(exc).__name__, exc)
        return None


async def close_mail_pool(pool: ArqRedis | None) -> None:
    """Pool schließen (Shutdown)."""
    if pool is not None:
        await pool.aclose()


def mail_queue_from_pool(pool: ArqRedis | None) -> MailQueue | None:
    """Pool → `MailQueue` (oder `None`, wenn kein Pool)."""
    return ArqMailQueue(pool) if pool is not None else None
