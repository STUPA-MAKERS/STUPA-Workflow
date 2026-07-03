"""arq worker: entry points + budget rollup refresh.

No-op ``ping`` (container healthcheck) plus ``refresh_budget_stats``: refreshes the
rollup MVs (``mv_budget_usage``/``mv_status_distribution``) ``CONCURRENTLY`` via a
nightly cron. Status changes/vote-close trigger the same job. ``CONCURRENTLY`` needs
an AUTOCOMMIT connection, hence a dedicated engine.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from arq import cron, func
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.modules.budget.stats import BudgetStatsService
from worker.deadlines import on_startup as deadlines_on_startup
from worker.deadlines import process_deadlines
from worker.mail import on_startup as mail_on_startup
from worker.mail import send_mail
from worker.pdf import on_startup as pdf_on_startup
from worker.pdf import render_pdf
from worker.protocol import render_protocol
from worker.retention import process_retention
from worker.scan import on_startup as scan_on_startup
from worker.scan import scan_attachment
from worker.task_reminders import process_task_reminders
from worker.webhook import deliver_webhook
from worker.webhook import on_startup as webhook_on_startup


async def ping(ctx: dict[str, object]) -> str:
    """Placeholder task."""
    return "pong"


# Hard per-job deadline for ``deliver_webhook``: it shares the arq worker with mail,
# scan, render and crons, so a slow/hostile target must not hold a slot to the arq
# default (300 s). Second bound below the service's ``webhook_timeout_seconds`` cap.
_WEBHOOK_JOB_TIMEOUT_SECONDS = 30.0


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Worker init: mail, scan, PDF-render and webhook deps."""
    await mail_on_startup(ctx)
    await scan_on_startup(ctx)
    await pdf_on_startup(ctx)
    await webhook_on_startup(ctx)
    await deadlines_on_startup(ctx)


@lru_cache(maxsize=1)
def _budget_engine() -> AsyncEngine:  # pragma: no cover
    """Single AUTOCOMMIT engine (worker lifetime); ``REFRESH ... CONCURRENTLY`` must
    not run in a transaction. Cached to avoid a pool leak per refresh."""
    return create_async_engine(
        os.environ.get("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag"),
        isolation_level="AUTOCOMMIT",
    )


def _budget_sessionmaker() -> async_sessionmaker[AsyncSession]:  # pragma: no cover
    """Sessionmaker on the reused engine (injected in tests via
    ``ctx['budget_sessionmaker']``)."""
    return async_sessionmaker(_budget_engine(), expire_on_commit=False)


async def refresh_budget_stats(ctx: dict[str, Any]) -> str:
    """Recompute both budget rollup MVs (CONCURRENTLY)."""
    maker: Callable[[], Any] = ctx.get("budget_sessionmaker") or _budget_sessionmaker()
    async with maker() as session:
        await BudgetStatsService(session).refresh(concurrently=True)
    return "ok"


async def _shutdown(ctx: dict[str, Any]) -> None:  # pragma: no cover
    """Dispose the cached budget engine on worker stop (release the pool)."""
    if _budget_engine.cache_info().currsize:
        await _budget_engine().dispose()
        _budget_engine.cache_clear()


class WorkerSettings:
    functions = [
        ping,
        refresh_budget_stats,
        send_mail,
        scan_attachment,
        render_pdf,
        render_protocol,
        # Short per-job timeout so a slow/hostile webhook target cannot hold a shared
        # worker slot to the arq default (300 s).
        func(deliver_webhook, timeout=_WEBHOOK_JOB_TIMEOUT_SECONDS),
        process_deadlines,
        process_task_reminders,
        process_retention,
    ]
    cron_jobs = [
        cron(refresh_budget_stats, hour=3, minute=0),
        # GDPR retention: daily anonymize terminal applications + purge expired
        # sessions/magic-links. Budget data is left untouched.
        cron(process_retention, hour=3, minute=30),
        # Scan deadlines/votes every minute — idempotent + SKIP LOCKED.
        cron(process_deadlines, second=0),
        # Task reminders hourly — thresholds in days; task_reminder_log prevents
        # duplicate sends.
        cron(process_task_reminders, minute=10),
    ]
    on_startup = _on_startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
