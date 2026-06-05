"""arq Worker — Skelett (T-01).

Eine No-op-Task + Redis-Anbindung, damit `arq --check worker.main.WorkerSettings`
greift (Container-Healthcheck). Echte Tasks/Cron (deadlines, retries, rollups): T-02+.
"""

import os

from arq.connections import RedisSettings


async def ping(ctx: dict[str, object]) -> str:
    """Platzhalter-Task."""
    return "pong"


class WorkerSettings:
    functions = [ping]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
