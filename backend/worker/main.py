"""arq worker: entry points and budget rollup refresh.

`ping` does nothing and serves the container healthcheck. A nightly cron runs
`refresh_budget_stats`, which refreshes the rollup materialized views
`mv_budget_usage` and `mv_status_distribution` with `CONCURRENTLY`. A status change
or a vote close triggers the same job. `CONCURRENTLY` needs an AUTOCOMMIT connection,
so the module keeps a dedicated engine.
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
from worker.backup import create_backup, restore_backup, scheduled_backup
from worker.backup import on_startup as backup_on_startup
from worker.deadlines import on_startup as deadlines_on_startup
from worker.deadlines import process_deadlines
from worker.mail import on_startup as mail_on_startup
from worker.mail import send_mail
from worker.protocol import on_startup as protocol_on_startup
from worker.protocol import render_protocol
from worker.retention import process_retention
from worker.scan import on_startup as scan_on_startup
from worker.scan import scan_attachment
from worker.task_reminders import process_task_reminders
from worker.webhook import deliver_webhook
from worker.webhook import on_startup as webhook_on_startup


async def ping(ctx: dict[str, object]) -> str:
    """Do nothing and serve the container healthcheck."""
    return "pong"


# Hard per-job deadline for `deliver_webhook`. The task shares the arq worker with mail,
# scan, render and the crons. A slow or hostile target must not hold a slot for the
# arq default of 300 s. This bound sits one level below the service cap
# `webhook_timeout_seconds`.
_WEBHOOK_JOB_TIMEOUT_SECONDS = 30.0

# A backup dumps the whole database and mirrors the attachment bucket, and a restore
# puts both back. Neither fits the arq default of 300 s on a real dataset. The bound
# sits one level above the subprocess timeout `backup_subprocess_timeout_seconds`.
_BACKUP_JOB_TIMEOUT_SECONDS = 7200.0


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Set up the mail, scan, protocol render, webhook and deadline dependencies."""
    await mail_on_startup(ctx)
    await scan_on_startup(ctx)
    await protocol_on_startup(ctx)
    await webhook_on_startup(ctx)
    await deadlines_on_startup(ctx)
    await backup_on_startup(ctx)


@lru_cache(maxsize=1)
def _budget_engine() -> AsyncEngine:  # pragma: no cover
    """Return the single AUTOCOMMIT engine for the worker lifetime.

    `REFRESH ... CONCURRENTLY` must not run inside a transaction. The cache stops a
    pool leak on every refresh.
    """
    return create_async_engine(
        os.environ.get("DATABASE_URL", "postgresql+asyncpg://app:pw@db/antrag"),
        isolation_level="AUTOCOMMIT",
    )


def _budget_sessionmaker() -> async_sessionmaker[AsyncSession]:  # pragma: no cover
    """Return a sessionmaker on the reused engine.

    Tests inject one through `ctx['budget_sessionmaker']`.
    """
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
        render_protocol,
        func(deliver_webhook, timeout=_WEBHOOK_JOB_TIMEOUT_SECONDS),
        process_deadlines,
        process_task_reminders,
        process_retention,
        func(create_backup, timeout=_BACKUP_JOB_TIMEOUT_SECONDS),
        func(restore_backup, timeout=_BACKUP_JOB_TIMEOUT_SECONDS),
        func(scheduled_backup, timeout=_BACKUP_JOB_TIMEOUT_SECONDS),
    ]
    cron_jobs = [
        cron(refresh_budget_stats, hour=3, minute=0),
        # GDPR retention: anonymize terminal applications once a day and purge expired
        # sessions and magic links. The job does not touch budget data.
        cron(process_retention, hour=3, minute=30),
        # Scan deadlines and votes every minute. The scan is idempotent and uses
        # SKIP LOCKED.
        cron(process_deadlines, second=0),
        # Task reminders run hourly. The thresholds are in days. The task_reminder_log
        # table prevents duplicate sends.
        cron(process_task_reminders, minute=10),
        # Nightly backup. It runs after the retention job, so the archive holds the
        # already-anonymized state rather than PII that retention is about to drop.
        cron(scheduled_backup, hour=4, minute=0),
    ]
    on_startup = _on_startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
