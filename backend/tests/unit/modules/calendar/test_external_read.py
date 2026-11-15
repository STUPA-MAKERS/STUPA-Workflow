"""Unit: the read of an external feed in a process of its own.

§F/meetings/calendar/000974: the worker stops a read that does not end, and stores the
cause ``timeout``.
"""

from __future__ import annotations

import time
from datetime import date
from multiprocessing.connection import Connection
from multiprocessing.connection import Pipe as pipe

import pytest

from app.modules.calendar.external_read import parse_into, read_feed, read_in_process

TODAY = date(2026, 11, 15)
FEED = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:a\r\n"
    b"DTSTART:20261120T100000Z\r\nSUMMARY:Sitzung\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


def never_returns(conn: Connection, data: bytes, today: date) -> None:
    """Stand in for a read that does not end."""
    time.sleep(3600)


def ends_silent(conn: Connection, data: bytes, today: date) -> None:
    """Stand in for a child that ends without an answer."""
    conn.close()


def _sent(data: bytes) -> object:
    receiver, sender = pipe(duplex=False)
    parse_into(sender, data, TODAY)
    return receiver.recv()


def test_the_child_sends_the_entries() -> None:
    entries = _sent(FEED)
    assert isinstance(entries, tuple)
    assert [e.title for e in entries] == ["Sitzung"]


def test_the_child_sends_none_for_bytes_that_are_no_calendar() -> None:
    assert _sent(b"kein Kalender") is None


@pytest.mark.asyncio
async def test_a_read_in_a_process_gives_the_entries() -> None:
    entries, error = await read_feed(FEED, TODAY)
    assert error is None
    assert entries is not None
    assert [e.starts_on for e in entries] == [date(2026, 11, 20)]


def test_bytes_that_are_no_calendar_give_format() -> None:
    assert read_in_process(b"kein Kalender", TODAY) == (None, "format")


def test_a_read_that_does_not_end_gives_timeout() -> None:
    started = time.monotonic()
    assert read_in_process(FEED, TODAY, 0.5, never_returns) == (None, "timeout")
    assert time.monotonic() - started < 30


def test_a_child_without_an_answer_gives_format() -> None:
    assert read_in_process(FEED, TODAY, 30, ends_silent) == (None, "format")
