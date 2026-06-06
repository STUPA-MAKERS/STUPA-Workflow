"""arq Worker — T-01-Skelett + Budget-Rollup-Refresh (T-17).

No-op-``ping`` (Container-Healthcheck) plus ``refresh_budget_stats``: aktualisiert die
Rollup-MVs (``mv_budget_usage``/``mv_status_distribution``) ``CONCURRENTLY`` per
nächtlichem Cron (data-model §3). Statuswechsel/Vote-Close stoßen denselben Job an
(Flow-Engine, T-14). ``CONCURRENTLY`` braucht eine AUTOCOMMIT-Verbindung → eigene Engine.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.modules.budget.stats import BudgetStatsService
from worker.mail import on_startup as mail_on_startup
from worker.mail import send_mail


async def ping(ctx: dict[str, object]) -> str:
    """Platzhalter-Task."""
    return "pong"


@lru_cache(maxsize=1)
def _budget_engine() -> AsyncEngine:  # pragma: no cover
    """Einmalige AUTOCOMMIT-Engine (Worker-Lebensdauer) — ``REFRESH … CONCURRENTLY``
    darf nicht in einer Transaktion laufen. Gecacht → kein Pool-Leak je Refresh."""
    return create_async_engine(
        os.environ.get("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag"),
        isolation_level="AUTOCOMMIT",
    )


def _budget_sessionmaker() -> async_sessionmaker[AsyncSession]:  # pragma: no cover
    """Sessionmaker auf der wiederverwendeten Engine. In Tests via
    ``ctx['budget_sessionmaker']`` injiziert."""
    return async_sessionmaker(_budget_engine(), expire_on_commit=False)


async def refresh_budget_stats(ctx: dict[str, Any]) -> str:
    """Beide Budget-Rollup-MVs neu berechnen (CONCURRENTLY)."""
    maker: Callable[[], Any] = ctx.get("budget_sessionmaker") or _budget_sessionmaker()
    async with maker() as session:
        await BudgetStatsService(session).refresh(concurrently=True)
    return "ok"


async def _shutdown(ctx: dict[str, Any]) -> None:  # pragma: no cover
    """Gecachte Budget-Engine beim Worker-Stop sauber schließen (Pool freigeben)."""
    if _budget_engine.cache_info().currsize:
        await _budget_engine().dispose()
        _budget_engine.cache_clear()


class WorkerSettings:
    functions = [ping, refresh_budget_stats, send_mail]
    cron_jobs = [cron(refresh_budget_stats, hour=3, minute=0)]
    on_startup = mail_on_startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
