"""Worker (worker/main.py) — Unit-Deckung: ping + Budget-Rollup-Refresh (T-17)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.auth_fakes import FakeSession
from worker.main import (
    WorkerSettings,
    ping,
    process_deadlines,
    process_retention,
    refresh_budget_stats,
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
    # Nächtlicher Budget-Rollup + minütlicher Deadline-Scan (T-44) +
    # stündliche Aufgaben-Erinnerungen (#task-reminder) + tägliche DSGVO-Aufbewahrung
    # (#PII-Re-Add).
    assert len(WorkerSettings.cron_jobs) == 4


class _SessionCM:
    """Async-Context-Manager-Hülle um eine Fake-Session."""

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
    # Zwei REFRESH-Statements + commit (BudgetStatsService.refresh).
    assert session.committed == 1
