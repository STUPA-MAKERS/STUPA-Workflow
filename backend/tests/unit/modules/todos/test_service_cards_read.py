"""``TodoService``: the reads of several cards and of a tile with a scripted session."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.todos.service import TodoService
from app.shared.errors import NotFoundError
from tests.unit.modules.todos.fakes import (
    USER,
    FakeAccess,
    FakeFiles,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
)

OUT = object()


def _svc(session: ScriptedSession, links: FakeLinks | None = None, **kw: Any) -> TodoService:
    service = TodoService(
        session,  # type: ignore[arg-type]
        access=FakeAccess(**kw),  # type: ignore[arg-type]
        links=links or FakeLinks(),  # type: ignore[arg-type]
        files=FakeFiles(),  # type: ignore[arg-type]
    )

    async def _detail(*_a: Any) -> Any:
        return OUT

    async def _details(pairs: Any, _p: Any) -> Any:
        return [c.id for c, _b in pairs]

    service._detail = _detail  # type: ignore[method-assign]
    service._details = _details  # type: ignore[method-assign]
    return service


def _setup(**kw: Any) -> tuple[ScriptedSession, Any, Any, Any, TodoService]:
    b = board()
    col = column(b.id)
    c = card(b, col, **kw)
    session = ScriptedSession()
    session.put(b, col, c)
    return session, b, col, c, _svc(session)


async def test_cards_keep_the_order_and_leave_out_unknown_and_unreadable() -> None:
    session = ScriptedSession()
    readable, hidden = board(), board()
    first = card(readable, column(readable.id))
    second = card(readable, column(readable.id))
    secret = card(hidden, column(hidden.id))
    session.scalars_q[:] = [[first, second, secret], [readable, hidden]]

    class _Only(FakeAccess):
        async def can_read(self, b: Any, _p: Any) -> bool:
            return b.id == readable.id

    service = _svc(session)
    service.access = _Only()  # type: ignore[assignment]
    got = await service.cards([second.id, uuid.uuid4(), secret.id, first.id, second.id], USER)
    assert got == [second.id, first.id]


async def test_tile_of_an_archived_card_is_not_found() -> None:
    _session, _b, _col, c, service = _setup(archived_at=SimpleNamespace())
    with pytest.raises(NotFoundError):
        await service.tile(c.id, USER)
