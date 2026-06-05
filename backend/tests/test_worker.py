"""Worker-Skelett (worker/main.py) — Unit-Deckung."""

from __future__ import annotations

import pytest

from worker.main import WorkerSettings, ping


@pytest.mark.asyncio
async def test_ping_returns_pong() -> None:
    assert await ping({}) == "pong"


def test_worker_settings_registers_ping() -> None:
    assert ping in WorkerSettings.functions
    assert WorkerSettings.redis_settings is not None
