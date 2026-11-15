"""The watchdog of the worker: a worker that hangs ends its process.

§NF/compatibility/deploy/000975. A task on the event loop stores the time of each
beat. A thread beside the loop reads that time. When the loop made no beat for
`STALL_LIMIT_SECONDS`, the thread ends the process, and the compose file starts the
worker again. A health check alone does not do this, because compose does not restart a
container that is only unhealthy.

The thread ends the process with `os._exit`, because a blocked event loop runs no
handler of a signal and no clean stop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("worker.watchdog")

#: The longest time without a beat of the event loop.
STALL_LIMIT_SECONDS = 120.0
#: The time between two beats and between two checks.
BEAT_SECONDS = 5.0
#: The exit status of a worker that the watchdog ended.
EXIT_STALLED = 70


@dataclass(slots=True)
class Watchdog:
    """One beat on the loop and one check beside it.

    A test injects the clock and the exit call.
    """

    limit_seconds: float = STALL_LIMIT_SECONDS
    beat_seconds: float = BEAT_SECONDS
    clock: Callable[[], float] = time.monotonic
    exit: Callable[[int], Any] = os._exit
    stop: threading.Event = field(default_factory=threading.Event)
    last_beat: float = 0.0

    def beat(self) -> None:
        """Store the time of this beat."""
        self.last_beat = self.clock()

    def stalled(self) -> bool:
        """Tell whether the loop made no beat for longer than the limit."""
        return (self.clock() - self.last_beat) > self.limit_seconds

    async def beat_forever(self) -> None:
        """Beat on the event loop until the task is cancelled."""
        while True:
            self.beat()
            await asyncio.sleep(self.beat_seconds)

    def check(self) -> bool:
        """End the process when the loop is stalled. Return whether it was."""
        if not self.stalled():
            return False
        logger.critical(
            "the event loop made no beat for %.0f s, the worker ends its process",
            self.limit_seconds,
        )
        self.exit(EXIT_STALLED)
        return True

    def watch(self) -> None:
        """Check until the stop event is set or the loop is stalled."""
        while not self.stop.wait(self.beat_seconds):
            if self.check():
                return


async def watchdog_on_startup(ctx: dict[str, Any]) -> None:
    """Start the beat task and the check thread."""
    watchdog = Watchdog()
    watchdog.beat()
    thread = threading.Thread(target=watchdog.watch, name="worker-watchdog", daemon=True)
    ctx.update(watchdog=watchdog, watchdog_task=asyncio.create_task(watchdog.beat_forever()))
    thread.start()


async def watchdog_on_shutdown(ctx: dict[str, Any]) -> None:
    """Stop the check thread and the beat task."""
    watchdog = ctx.get("watchdog")
    task = ctx.get("watchdog_task")
    if isinstance(watchdog, Watchdog):
        watchdog.stop.set()
    if isinstance(task, asyncio.Task):
        task.cancel()
