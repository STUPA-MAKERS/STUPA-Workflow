"""The ticket side of the to-dos: open count, completeTodos and the readable cards."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.todos.hooks import TicketTodoBridge
from app.modules.todos.service import TodoService
from tests.unit.modules.todos.fakes import (
    USER,
    FakeAccess,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
)

TICKET = uuid.UUID(int=61)


class _Access(FakeAccess):
    def __init__(self, readable: set[uuid.UUID], **kw: Any) -> None:
        super().__init__(**kw)
        self.readable = readable

    async def can_read(self, board: Any, _principal: Any) -> bool:
        return board.id in self.readable


def _bridge(session: ScriptedSession, readable: set[uuid.UUID], **kw: Any) -> TicketTodoBridge:
    service = TodoService(
        session,  # type: ignore[arg-type]
        access=_Access(readable, **kw),  # type: ignore[arg-type]
        links=FakeLinks(),  # type: ignore[arg-type]
    )
    return TicketTodoBridge(session, service)  # type: ignore[arg-type]


def test_the_default_service() -> None:
    session = ScriptedSession()
    bridge = TicketTodoBridge(session)  # type: ignore[arg-type]
    assert bridge.todos.session is session


async def test_open_count_counts_readable_cards_only() -> None:
    seen, hidden = board(), board()
    rows = [(card(seen, column(seen.id)), seen), (card(hidden, column(hidden.id)), hidden)]
    bridge = _bridge(ScriptedSession(execute=[rows]), {seen.id})
    assert await bridge.open_count(TICKET, USER) == 1


async def test_complete_moves_the_cards_and_commits() -> None:
    b = board()
    col, done = column(b.id), column(b.id, "Erledigt", 1, is_done=True)
    c = card(b, col)
    session = ScriptedSession(execute=[[(c, b)]], scalars=[[col, done], [], [TICKET]])
    await _bridge(session, {b.id}).complete(TICKET, USER)
    assert c.column_id == done.id and session.committed == 1


async def test_complete_without_cards_without_account_or_without_a_move() -> None:
    b = board()
    col = column(b.id)
    c = card(b, col)
    empty = ScriptedSession(execute=[[]])
    await _bridge(empty, {b.id}).complete(TICKET, USER)
    assert empty.committed == 0
    nobody = ScriptedSession(execute=[[(c, b)]])
    await _bridge(nobody, {b.id}, me=None).complete(TICKET, USER)
    assert nobody.committed == 0
    no_done = ScriptedSession(execute=[[(c, b)]], scalars=[[col]])
    await _bridge(no_done, {b.id}).complete(TICKET, USER)
    assert no_done.committed == 0


async def test_readable_cards() -> None:
    seen, hidden = board(), board()
    a, z = uuid.uuid4(), uuid.uuid4()
    bridge = _bridge(ScriptedSession(execute=[[(a, seen), (z, hidden)]]), {seen.id})
    assert await bridge.readable_cards([a, z], USER) == {a}
    assert await bridge.readable_cards([], USER) == set()


async def test_complete_locks_the_boards_in_board_id_order() -> None:
    low, high = board(id=uuid.UUID(int=1)), board(id=uuid.UUID(int=2))
    first, second = card(high, column(high.id)), card(low, column(low.id))
    third = card(high, column(high.id))
    session = ScriptedSession(execute=[[(first, high), (second, low), (third, high)]])
    bridge = _bridge(session, {low.id, high.id})
    order: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def _complete(c: Any, b: Any, _actor: uuid.UUID) -> bool:
        order.append((b.id, c.id))
        return True

    bridge.todos.complete = _complete  # type: ignore[method-assign]
    await bridge.complete(TICKET, USER)
    assert order == [(low.id, second.id), (high.id, first.id), (high.id, third.id)]
    assert session.committed == 1
