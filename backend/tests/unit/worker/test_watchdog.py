"""Unit: the watchdog of the worker.

§NF/compatibility/deploy/000975: a worker whose event loop does not run for the limit
ends its process.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from worker.watchdog import (
    EXIT_STALLED,
    Watchdog,
    watchdog_on_shutdown,
    watchdog_on_startup,
)


class Clock:
    """A clock that a test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _watchdog(clock: Clock, exits: list[int]) -> Watchdog:
    return Watchdog(limit_seconds=120, beat_seconds=0.01, clock=clock, exit=exits.append)


def test_a_loop_that_beats_is_not_ended() -> None:
    clock, exits = Clock(), list[int]()
    watchdog = _watchdog(clock, exits)
    watchdog.beat()
    clock.now += 120
    assert watchdog.check() is False
    assert exits == []


def test_a_blocked_loop_ends_the_process() -> None:
    clock, exits = Clock(), list[int]()
    watchdog = _watchdog(clock, exits)
    watchdog.beat()
    clock.now += 121
    assert watchdog.check() is True
    assert exits == [EXIT_STALLED]


def test_the_thread_ends_the_process_and_returns() -> None:
    clock, exits = Clock(), list[int]()
    watchdog = _watchdog(clock, exits)
    watchdog.beat()
    clock.now += 500
    thread = threading.Thread(target=watchdog.watch)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert exits == [EXIT_STALLED]


def test_the_thread_stops_at_the_stop_event() -> None:
    clock, exits = Clock(), list[int]()
    watchdog = _watchdog(clock, exits)
    watchdog.beat()
    thread = threading.Thread(target=watchdog.watch)
    thread.start()
    watchdog.stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert exits == []


async def test_the_beat_task_stores_the_time() -> None:
    clock, exits = Clock(), list[int]()
    watchdog = _watchdog(clock, exits)
    task = asyncio.create_task(watchdog.beat_forever())
    clock.now = 2000.0
    await asyncio.sleep(0.05)
    task.cancel()
    assert watchdog.last_beat == 2000.0


async def test_startup_and_shutdown() -> None:
    ctx: dict[str, Any] = {}
    await watchdog_on_startup(ctx)
    watchdog, task = ctx["watchdog"], ctx["watchdog_task"]
    assert isinstance(watchdog, Watchdog)
    assert watchdog.stalled() is False
    await watchdog_on_shutdown(ctx)
    await asyncio.sleep(0)
    assert watchdog.stop.is_set()
    assert task.cancelled()
    await watchdog_on_shutdown({})
