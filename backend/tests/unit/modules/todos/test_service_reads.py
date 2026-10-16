"""``TodoService``: the reads across boards and the agenda coupling."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.todos.models import TodoLink
from app.modules.todos.service import TodoService, berlin_today
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from tests.unit.modules.todos.fakes import (
    ME,
    USER,
    FakeAccess,
    FakeFiles,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
    label,
)


def _sql(stmt: object) -> str:
    from sqlalchemy.dialects import postgresql

    return str(stmt.compile(dialect=postgresql.dialect()))  # type: ignore[attr-defined]


TOKEN = Principal(sub="t", scope_permissions=frozenset({"vote.cast"}))
ITEM = uuid.UUID(int=51)


def _svc(session: ScriptedSession, **kw: Any) -> TodoService:
    return TodoService(
        session,  # type: ignore[arg-type]
        access=FakeAccess(**kw),  # type: ignore[arg-type]
        links=FakeLinks(),  # type: ignore[arg-type]
        files=FakeFiles(),  # type: ignore[arg-type]
    )


async def test_mine_needs_the_scope_and_an_account() -> None:
    with pytest.raises(ForbiddenError):
        await _svc(ScriptedSession()).mine(TOKEN)
    out = await _svc(ScriptedSession(), me=None).mine(USER)
    assert out.items == [] and out.due_soon_count == 0
    out = await _svc(ScriptedSession(execute=[[]])).mine(USER)
    assert out.items == []


async def test_mine_lists_the_cards_and_counts_the_due_soon_ones() -> None:
    b = board(name="StuPa")
    col = column(b.id, "In Arbeit")
    lab = label(b.id)
    today = berlin_today()
    soon = card(b, col, due_date=today + timedelta(days=7))
    late = card(b, col, due_date=today + timedelta(days=8))
    none = card(b, col)
    session = ScriptedSession(
        execute=[
            [(soon, b, col), (late, b, col), (none, b, col)],
            [(soon.id, lab.id), (late.id, uuid.uuid4())],
            [],
            [],
            [],
        ],
        scalars=[[], [lab]],
    )
    out = await _svc(session).mine(USER)
    assert [i.id for i in out.items] == [soon.id, late.id, none.id]
    assert out.due_soon_count == 1
    assert out.items[0].board_name == "StuPa" and out.items[0].column_name == "In Arbeit"
    assert [x.name for x in out.items[0].labels] == ["Wichtig"]
    assert out.items[1].labels == []


async def test_linked_sorts_open_first_then_by_due_date() -> None:
    assert await _svc(ScriptedSession()).linked("ticket", uuid.uuid4(), TOKEN) == []
    assert await _svc(ScriptedSession(execute=[[]])).linked("ticket", uuid.uuid4(), USER) == []
    b = board()
    open_col, done = column(b.id), column(b.id, "Erledigt", 1, is_done=True)
    today = berlin_today()
    a = card(b, open_col, title="b", due_date=today)
    z = card(b, open_col, title="a")
    finished = card(b, done, title="c", due_date=today)
    earlier = card(b, open_col, title="d", due_date=today - timedelta(days=1))
    session = ScriptedSession(
        execute=[[(finished, b, done), (z, b, open_col), (a, b, open_col), (earlier, b, open_col)]],
        scalars=[[]],
    )
    out = await _svc(session).linked("meeting", uuid.uuid4(), USER)
    assert [c.title for c in out] == ["d", "b", "a", "c"]
    assert out[-1].is_done is True
    assert "todo_link.meeting_id" in str(session.statements[0])


async def test_search_is_scoped() -> None:
    assert await _svc(ScriptedSession()).search("plakat", TOKEN, limit=5) == []
    b = board()
    col = column(b.id)
    c = card(b, col)
    session = ScriptedSession(execute=[[(c, b, col)]])
    assert await _svc(session).search("plakat", USER, limit=5) == [(c, b, col)]


async def test_card_for_agenda_rules() -> None:
    gid = uuid.uuid4()
    b = board(gremium_id=gid)
    col = column(b.id)
    live, archived = card(b, col), card(b, col, archived_at=b.created_at)
    personal = board(kind="personal", gremium_id=None, owner_id=ME)
    mine = card(personal, column(personal.id))
    session = ScriptedSession(scalar=[live, archived, live, mine, live])
    session.put(b, live, archived, personal, mine)
    service = _svc(session)
    assert await service.card_for_agenda(live.id, gid, USER) is live
    # The board lock comes first, then the card lock: the order of every card write.
    board_lock, card_lock = (_sql(stmt) for stmt in session.statements[:2])
    assert board_lock.startswith("SELECT todo_board.id") and "FOR UPDATE" in board_lock
    assert "FROM todo_card" in card_lock and "FOR NO KEY UPDATE" in card_lock
    with pytest.raises(ValidationProblem) as exc:
        await service.card_for_agenda(archived.id, gid, USER)
    assert exc.value.code == "todo_archived"
    for card_id, gremium in ((live.id, uuid.uuid4()), (mine.id, gid)):
        with pytest.raises(ValidationProblem) as exc:
            await service.card_for_agenda(card_id, gremium, USER)
        assert exc.value.code == "todo_wrong_board"
    with pytest.raises(NotFoundError):
        await _svc(session, read=False).card_for_agenda(live.id, gid, USER)


async def test_link_agenda_item_once() -> None:
    b = board()
    c = card(b, column(b.id))
    stamp = b.updated_at
    session = ScriptedSession(scalar=[uuid.uuid4(), None, None])
    session.put(b)
    service = _svc(session)
    await service.link_agenda_item(c, ITEM, USER)
    assert session.added == []
    await service.link_agenda_item(c, ITEM, USER)
    (new,) = [o for o in session.added if isinstance(o, TodoLink)]
    assert new.agenda_item_id == ITEM and b.updated_at != stamp
    orphan = card(board(), column(uuid.uuid4()))
    await service.link_agenda_item(orphan, ITEM, USER)
    assert session.committed == 0
