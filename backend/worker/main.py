"""arq Worker — T-01-Skelett + Budget-Rollup-Refresh (T-17).

No-op-``ping`` (Container-Healthcheck) plus ``refresh_budget_stats``: aktualisiert die
Rollup-MVs (``mv_budget_usage``/``mv_status_distribution``) ``CONCURRENTLY`` per
nächtlichem Cron (data-model §3). Statuswechsel/Vote-Close stoßen denselben Job an
(Flow-Engine, T-14). ``CONCURRENTLY`` braucht eine AUTOCOMMIT-Verbindung → eigene Engine.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.budget.stats import BudgetStatsService


async def ping(ctx: dict[str, object]) -> str:
    """Platzhalter-Task."""
    return "pong"


def _budget_sessionmaker() -> async_sessionmaker[AsyncSession]:  # pragma: no cover
    """AUTOCOMMIT-Sessionmaker (Prod/Worker) — ``REFRESH … CONCURRENTLY`` darf nicht in
    einer Transaktion laufen. In Tests via ``ctx['budget_sessionmaker']`` injiziert."""
    engine = create_async_engine(
        os.environ.get("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag"),
        isolation_level="AUTOCOMMIT",
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def refresh_budget_stats(ctx: dict[str, Any]) -> str:
    """Beide Budget-Rollup-MVs neu berechnen (CONCURRENTLY)."""
    maker: Callable[[], Any] = ctx.get("budget_sessionmaker") or _budget_sessionmaker()
    async with maker() as session:
        await BudgetStatsService(session).refresh(concurrently=True)
    return "ok"


class WorkerSettings:
    functions = [ping, refresh_budget_stats]
    cron_jobs = [cron(refresh_budget_stats, hour=3, minute=0)]
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
