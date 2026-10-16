"""The to-do worker: the archive cron and the ``todo_due`` reminder (no database)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

import worker.todos as wt
from app.modules.todos.models import TodoEvent
from app.settings import load_settings
from tests.unit.modules.todos.fakes import ME, OTHER, ScriptedSession, board, card, column

SETTINGS = load_settings()
# 08:00 in Berlin (CEST): the reminder window is open.
MORNING = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
# 06:30 in Berlin: too early.
EARLY = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


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
    return {"todos_sessionmaker": _Maker(session), "settings": SETTINGS, **kw}


def test_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    monkeypatch.setattr(wt, "get_sessionmaker", lambda: marker)
    assert wt._sessionmaker({}) is marker
    queue = object()
    assert wt._mail_queue({"mail_queue": queue}) is queue
    assert wt._mail_queue({}) is None
    assert isinstance(wt._mail_queue({"redis": object()}), wt.ArqMailQueue)


async def test_archive_archives_the_due_cards() -> None:
    b = board()
    done = column(b.id, "Erledigt", is_done=True)
    old = card(b, done, completed_at=datetime(2026, 8, 1, tzinfo=UTC))
    session = ScriptedSession(execute=[[(old, b)]])
    assert await wt.archive_done_todos(_ctx(session), now=MORNING) == 1
    assert old.archived_at == MORNING and b.updated_at == MORNING
    (event,) = [o for o in session.added if isinstance(o, TodoEvent)]
    assert event.kind == "archived" and event.actor_id is None
    assert session.committed == 1
    sql = str(session.statements[0])
    assert "make_interval" in sql and "FOR UPDATE" in sql


async def test_archive_with_nothing_due() -> None:
    session = ScriptedSession(execute=[[]])
    assert await wt.archive_done_todos(_ctx(session)) == 0
    assert session.committed == 0


async def test_due_waits_for_the_morning() -> None:
    session = ScriptedSession()
    assert await wt.process_todo_due(_ctx(session), now=EARLY) == 0
    assert session.statements == []


async def test_due_reminds_once_and_skips_a_failing_card(monkeypatch: pytest.MonkeyPatch) -> None:
    b = board()
    col = column(b.id)
    ok, quiet, broken = card(b, col), card(b, col), card(b, col)
    calls: list[tuple[Any, list[Any], date]] = []

    async def _send(_s: Any, *, card: Any, assignee_ids: list[Any], due: date, **_kw: Any) -> bool:
        calls.append((card, assignee_ids, due))
        if card is broken:
            raise RuntimeError("smtp")
        return card is ok

    monkeypatch.setattr(wt, "send_todo_due", _send)
    asked = _members(monkeypatch, {ME, OTHER})
    session = ScriptedSession(
        execute=[[(ok, b), (quiet, b), (broken, b)]], scalars=[[ME, OTHER], [], [ME]]
    )
    assert await wt.process_todo_due(_ctx(session), now=MORNING) == 1
    # One member read per board, not per card.
    assert asked == [b.id]
    tomorrow = date(2026, 10, 2)
    assert [c[2] for c in calls] == [tomorrow] * 3
    assert calls[0][1] == [ME, OTHER]
    assert ok.due_reminded_on == tomorrow and quiet.due_reminded_on == tomorrow
    assert broken.due_reminded_on is None
    assert session.committed == 1
    assert "IS DISTINCT FROM" in str(session.statements[0])


def _members(monkeypatch: pytest.MonkeyPatch, ids: set[Any]) -> list[Any]:
    asked: list[Any] = []

    class _Access:
        def __init__(self, _session: object) -> None:
            pass

        async def member_ids(self, b: Any) -> set[Any]:
            asked.append(b.id)
            return ids

    monkeypatch.setattr(wt, "BoardAccess", _Access)
    return asked


async def test_due_skips_an_assignee_who_left_the_board(monkeypatch: pytest.MonkeyPatch) -> None:
    b = board()
    col = column(b.id)
    one, gone = card(b, col), card(b, col)
    calls: list[list[Any]] = []

    async def _send(_s: Any, *, assignee_ids: list[Any], **_kw: Any) -> bool:
        calls.append(assignee_ids)
        return bool(assignee_ids)

    monkeypatch.setattr(wt, "send_todo_due", _send)
    _members(monkeypatch, {ME})
    session = ScriptedSession(execute=[[(one, b), (gone, b)]], scalars=[[ME, OTHER], [OTHER]])
    assert await wt.process_todo_due(_ctx(session), now=MORNING) == 1
    assert calls == [[ME], []]
    assert gone.due_reminded_on == date(2026, 10, 2)


async def test_due_without_cards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wt, "load_settings", lambda: SETTINGS)
    session = ScriptedSession(execute=[[]])
    ctx = _ctx(session)
    del ctx["settings"]
    assert await wt.process_todo_due(ctx, now=MORNING) == 0
    assert session.committed == 0 and len(session.statements) == 1
