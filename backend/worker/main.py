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

from app.db import get_sessionmaker
from app.modules.budget.stats import BudgetStatsService
from app.modules.flow.dispatch import build_worker_dispatcher
from worker.audit_verify import process_audit_verification
from worker.backup import create_backup, restore_backup, scheduled_backup
from worker.backup import on_startup as backup_on_startup
from worker.cd_builtin import migrate_builtin_cd_logos
from worker.cd_builtin import on_startup as cd_builtin_on_startup
from worker.deadlines import on_startup as deadlines_on_startup
from worker.deadlines import process_deadlines
from worker.files_drafts import purge_draft_attachments
from worker.mail import on_startup as mail_on_startup
from worker.mail import send_mail
from worker.protocol import backfill_public_protocols, heal_public_protocols, render_protocol
from worker.protocol import on_startup as protocol_on_startup
from worker.retention import process_retention
from worker.scan import on_startup as scan_on_startup
from worker.scan import scan_attachment
from worker.task_reminders import process_task_reminders
from worker.tickets import anonymize_tickets
from worker.todos import archive_done_todos
from worker.webhook import deliver_webhook
from worker.webhook import on_startup as webhook_on_startup


async def ping(ctx: dict[str, object]) -> str:
    """Do nothing and serve the container healthcheck."""
    return "pong"


#: Hard deadline of ``deliver_webhook``. The task shares the worker with mail, scan,
#: render and the crons, so a slow or hostile target must not hold a slot for the arq
#: default of 300 s. It sits one level below ``webhook_timeout_seconds``.
_WEBHOOK_JOB_TIMEOUT_SECONDS = 30.0

#: Deadline of a backup or restore, which dumps or restores the whole database and the
#: attachment bucket; neither fits the arq default of 300 s. It sits one level above
#: ``backup_subprocess_timeout_seconds``.
_BACKUP_JOB_TIMEOUT_SECONDS = 7200.0

#: Deadline of the nightly audit-chain check. It reads the whole ``audit_entry`` table.
#: With the arq default of 300 s, arq cancels it on a large log, the transaction rolls
#: back and no ``audit_verification`` row is stored. It equals the backup bound, because
#: a backup reads the same table and more.
_AUDIT_VERIFY_JOB_TIMEOUT_SECONDS = 7200.0


async def _on_startup(ctx: dict[str, Any]) -> None:
    """Set up the mail, scan, protocol render, webhook and deadline dependencies.

    It also enqueues the one-off conversion of the vendored CD logos. That step runs
    after the protocol start-up, because the conversion job reads the object storage
    that the protocol start-up builds.

    It also builds the flow action dispatcher once. The deadline cron, the automatic
    transitions and the vote auto-close read it from `ctx['flow_dispatcher']`, so a
    transition that the worker fires runs the same actions as one from the API.
    """
    await mail_on_startup(ctx)
    await scan_on_startup(ctx)
    await protocol_on_startup(ctx)
    await webhook_on_startup(ctx)
    await deadlines_on_startup(ctx)
    await backup_on_startup(ctx)
    await cd_builtin_on_startup(ctx)
    ctx["flow_dispatcher"] = build_worker_dispatcher(
        ctx.get("redis"), get_sessionmaker(), ctx.get("settings")
    )


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
    """arq settings of the worker: the jobs, the crons and the lifecycle hooks.

    The crons: the budget stats at 03:00. GDPR retention at 03:30 anonymizes
    terminal applications and purges expired sessions and magic links; it does not touch
    budget data. Ticket retention at 03:45 anonymizes tickets closed longer than
    ``tickets.retentionMonths`` (reporter, context, attachments). The to-do archive at
    03:50 archives cards longer than ``archive_after_days`` in the done column. The
    deadline and vote scan runs every minute; it is idempotent and uses SKIP LOCKED.
    Task reminders run hourly (thresholds in days); ``task_reminder_log`` prevents
    duplicate sends. Expired wizard drafts go hourly with their objects. The public
    protocol heal builds the public versions that a failed or raced backfill left out,
    so they appear without a new switch of the gremium flag. The backup at 04:00 runs
    after retention, so the archive holds the anonymized state rather than PII that
    retention is about to drop. The audit-chain check at 04:30 does not depend on the
    backup and runs also when backups are off or failed.
    """
    functions = [
        ping,
        refresh_budget_stats,
        send_mail,
        scan_attachment,
        render_protocol,
        backfill_public_protocols,
        heal_public_protocols,
        func(deliver_webhook, timeout=_WEBHOOK_JOB_TIMEOUT_SECONDS),
        process_deadlines,
        process_task_reminders,
        process_retention,
        purge_draft_attachments,
        anonymize_tickets,
        archive_done_todos,
        func(process_audit_verification, timeout=_AUDIT_VERIFY_JOB_TIMEOUT_SECONDS),
        func(create_backup, timeout=_BACKUP_JOB_TIMEOUT_SECONDS),
        func(restore_backup, timeout=_BACKUP_JOB_TIMEOUT_SECONDS),
        func(scheduled_backup, timeout=_BACKUP_JOB_TIMEOUT_SECONDS),
        migrate_builtin_cd_logos,
    ]
    cron_jobs = [
        cron(refresh_budget_stats, hour=3, minute=0),
        cron(process_retention, hour=3, minute=30),
        cron(anonymize_tickets, hour=3, minute=45),
        cron(archive_done_todos, hour=3, minute=50),
        cron(process_deadlines, second=0),
        cron(process_task_reminders, minute=10),
        cron(purge_draft_attachments, minute=20),
        cron(heal_public_protocols, minute=40),
        cron(scheduled_backup, hour=4, minute=0),
        cron(
            process_audit_verification,
            hour=4,
            minute=30,
            timeout=_AUDIT_VERIFY_JOB_TIMEOUT_SECONDS,
        ),
    ]
    on_startup = _on_startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://redis:6379/0")
    )
