"""Board creation: the default columns, the gremium board and the personal board."""

from __future__ import annotations

import uuid

from app.modules.todos.boards import (
    add_default_columns,
    ensure_gremium_board,
    ensure_personal_board,
)
from app.modules.todos.models import TodoBoard, TodoColumn
from tests.unit.modules.todos.fakes import ME, ScriptedSession


def _columns(session: ScriptedSession) -> list[TodoColumn]:
    return [o for o in session.added if isinstance(o, TodoColumn)]


def test_default_columns_end_with_the_done_column() -> None:
    session = ScriptedSession()
    add_default_columns(session, uuid.uuid4())  # type: ignore[arg-type]
    cols = _columns(session)
    assert [c.name for c in cols] == ["Offen", "In Arbeit", "Wartet", "Erledigt"]
    assert [c.is_done for c in cols] == [False, False, False, True]
    assert [c.position for c in cols] == [0, 1, 2, 3]


async def test_a_gremium_board_is_created_once() -> None:
    gid = uuid.uuid4()
    session = ScriptedSession(scalar=[None])
    assert await ensure_gremium_board(session, gid, "StuPa") is True  # type: ignore[arg-type]
    (created,) = [o for o in session.added if isinstance(o, TodoBoard)]
    assert (created.name, created.kind, created.gremium_id) == ("StuPa", "gremium", gid)
    assert len(_columns(session)) == 4
    assert session.committed == 0
    again = ScriptedSession(scalar=[uuid.uuid4()])
    assert await ensure_gremium_board(again, gid, "StuPa") is False  # type: ignore[arg-type]
    assert again.added == []


async def test_the_personal_board_is_created_on_first_read() -> None:
    session = ScriptedSession(scalar=[None, uuid.uuid4()])
    assert await ensure_personal_board(session, ME) is True  # type: ignore[arg-type]
    assert "ON CONFLICT" in str(session.statements[-1].compile(dialect=_pg()))
    assert len(_columns(session)) == 4
    assert session.committed == 1


async def test_the_personal_board_exists_or_a_parallel_read_won() -> None:
    exists = ScriptedSession(scalar=[uuid.uuid4()])
    assert await ensure_personal_board(exists, ME) is False  # type: ignore[arg-type]
    raced = ScriptedSession(scalar=[None, None])
    assert await ensure_personal_board(raced, ME) is False  # type: ignore[arg-type]
    assert raced.added == [] and raced.committed == 0


def _pg():  # the dialect object
    from sqlalchemy.dialects import postgresql

    return postgresql.dialect()
