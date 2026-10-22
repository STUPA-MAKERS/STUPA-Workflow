"""The poll worker: the reminder 24 h before the end (no database)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

import worker.polls as wp
from app.settings import load_settings
from tests.unit.modules.todos.fakes import ScriptedSession

SETTINGS = load_settings()
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


class _Maker:
    def __init__(self, session: ScriptedSession) -> None:
        self.session = session

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> ScriptedSession:
        return self.session

    async def __aexit__(self, *_a: object) -> None:
        return None


def _ctx(session: ScriptedSession, **kw: Any) -> dict[str, Any]:
    return {"polls_sessionmaker": _Maker(session), "settings": SETTINGS, **kw}


def test_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    monkeypatch.setattr(wp, "get_sessionmaker", lambda: marker)
    assert wp._sessionmaker({}) is marker
    queue = object()
    assert wp._mail_queue({"mail_queue": queue}) is queue
    assert wp._mail_queue({}) is None
    assert isinstance(wp._mail_queue({"redis": object()}), wp.ArqMailQueue)


async def test_reminds_once_and_skips_a_failing_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    ok, quiet, broken = (SimpleNamespace(id=uuid4(), reminded_at=None) for _ in range(3))
    calls: list[Any] = []

    async def _send(_s: Any, *, vote: Any, reminder: bool, now: datetime, **_kw: Any) -> bool:
        calls.append((vote, reminder, now))
        if vote is broken:
            raise RuntimeError("smtp")
        return vote is ok

    monkeypatch.setattr(wp, "send_poll_mail", _send)
    session = ScriptedSession(scalars=[[ok, quiet, broken]])
    assert await wp.process_poll_reminders(_ctx(session), now=NOW) == 1
    assert [c[0] for c in calls] == [ok, quiet, broken]
    assert all(c[1] is True and c[2] == NOW for c in calls)
    assert ok.reminded_at == NOW
    assert quiet.reminded_at == NOW
    assert broken.reminded_at is None
    assert session.committed == 1
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "vote.reminded_at IS NULL" in sql
    assert "vote.meeting_id IS NULL" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql


async def test_nothing_due_commits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wp, "load_settings", lambda: SETTINGS)
    session = ScriptedSession(scalars=[[]])
    ctx = {"polls_sessionmaker": _Maker(session)}
    assert await wp.process_poll_reminders(ctx) == 0
    assert session.committed == 0
