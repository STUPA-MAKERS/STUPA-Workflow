"""Read the bytes of an external feed in a process of its own (§F/meetings/calendar/000974).

The feed is the input of another system, and `parse_feed` is plain Python that no
`await` interrupts. A read that never ends in the worker process stops each other job of
the worker. So the worker starts one child process for one read and kills it after
`READ_TIMEOUT_SECONDS`. The child sends the entries back through a pipe, or None for
bytes that are no calendar. A child that ends without an answer counts as bytes that are
no calendar.

The child starts with ``spawn`` and not with ``fork``, because the worker process holds
an event loop and open sockets that a forked child must not share.
"""

from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable
from datetime import date
from multiprocessing.connection import Connection
from typing import Protocol

from app.modules.calendar.external_feed import FeedEntry, FeedError, parse_feed
from app.modules.calendar.external_fetch import FetchError

#: The longest time of one read, the start of the child included.
READ_TIMEOUT_SECONDS = 10.0

#: The result of one read: the entries, or the cause of the failure.
Read = tuple[tuple[FeedEntry, ...] | None, FetchError | None]

#: The body of the child. A test gives one that never returns.
Target = Callable[[Connection, bytes, date], None]


class FeedReader(Protocol):
    """Turn the bytes of one feed into entries."""

    async def __call__(self, data: bytes, today: date) -> Read:
        """Read ``data``."""
        ...


def parse_into(conn: Connection, data: bytes, today: date) -> None:
    """Parse the feed and send the entries, or None for bytes that are no calendar."""
    try:
        conn.send(parse_feed(data, today))
    except FeedError:
        conn.send(None)
    finally:
        conn.close()


def _answer(conn: Connection) -> Read:
    """Take the answer of the child. A closed pipe without an answer is no calendar."""
    try:
        entries = conn.recv()
    except EOFError:
        return None, "format"
    return (None, "format") if entries is None else (entries, None)


def read_in_process(
    data: bytes,
    today: date,
    timeout_seconds: float = READ_TIMEOUT_SECONDS,
    target: Target = parse_into,
) -> Read:
    """Run one read in a child process and kill the child at the time limit."""
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    child = context.Process(target=target, args=(sender, data, today), daemon=True)
    child.start()
    sender.close()
    try:
        return _answer(receiver) if receiver.poll(timeout_seconds) else (None, "timeout")
    finally:
        child.kill()
        child.join()
        receiver.close()


async def read_feed(data: bytes, today: date) -> Read:
    """Read one feed in a child process without a block of the event loop."""
    return await asyncio.to_thread(read_in_process, data, today)
