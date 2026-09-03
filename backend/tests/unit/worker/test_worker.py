"""Worker (worker/main.py) unit coverage: ping and the budget rollup refresh (T-17)."""

from __future__ import annotations

from typing import Any

import pytest

from tests._support.auth_fakes import FakeSession
from worker.main import (
    WorkerSettings,
    ping,
    process_deadlines,
    process_retention,
    refresh_budget_stats,
    scheduled_backup,
)


@pytest.mark.asyncio
async def test_ping_returns_pong() -> None:
    assert await ping({}) == "pong"


def test_worker_settings_registers_tasks() -> None:
    assert ping in WorkerSettings.functions
    assert refresh_budget_stats in WorkerSettings.functions
    assert process_deadlines in WorkerSettings.functions
    assert process_retention in WorkerSettings.functions
    assert WorkerSettings.redis_settings is not None
    # Nightly budget rollup, deadline scan every minute (T-44), hourly task reminders
    #, daily DSGVO retention and the nightly backup.
    assert len(WorkerSettings.cron_jobs) == 5
    assert any(
        job.coroutine is scheduled_backup for job in WorkerSettings.cron_jobs
    ), "the nightly backup must be scheduled"


class _SessionCM:
    """Wrap a fake session in an async context manager."""

    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_refresh_budget_stats_uses_injected_sessionmaker() -> None:
    session = FakeSession()
    ctx: dict[str, Any] = {"budget_sessionmaker": lambda: _SessionCM(session)}
    assert await refresh_budget_stats(ctx) == "ok"
    # `BudgetStatsService.refresh` runs two REFRESH statements and one commit.
    assert session.committed == 1
