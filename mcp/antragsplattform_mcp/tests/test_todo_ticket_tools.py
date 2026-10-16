"""Tests for the to-do and ticket tools (WP3).

Each tool sends exactly one request. Optional arguments stay off the wire; a patch
keeps an explicit null so that it clears a field or unassigns.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.config import DEFAULT_SCOPE
from antragsplattform_mcp.tools import _GROUPS, _common, tickets, todos


class _FakeApi:
    """Record each request and answer with an empty object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def _record(
        self, method: str, path: str, kw: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((method, path, kw.get("json", kw.get("params"))))
        return {}

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("GET", path, kw)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("POST", path, kw)

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("PATCH", path, kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_groups_are_registered() -> None:
    assert todos in _GROUPS
    assert tickets in _GROUPS


def test_default_scope_requests_the_new_scopes() -> None:
    assert "todos:write" in DEFAULT_SCOPE.split()
    assert "tickets:write" in DEFAULT_SCOPE.split()


def test_todo_boards_without_and_with_gremium(fake_api: _FakeApi) -> None:
    asyncio.run(todos.todo_boards())
    asyncio.run(todos.todo_boards(gremium_id="g1"))
    assert fake_api.calls == [
        ("GET", "/todos/boards", {}),
        ("GET", "/todos/boards", {"gremiumId": "g1"}),
    ]


def test_todo_board_and_card_get(fake_api: _FakeApi) -> None:
    asyncio.run(todos.todo_board("b1"))
    asyncio.run(todos.todo_card_get("c1"))
    assert fake_api.calls == [
        ("GET", "/todos/boards/b1", None),
        ("GET", "/todos/cards/c1", None),
    ]


def test_todo_card_create_drops_unset_fields(fake_api: _FakeApi) -> None:
    card = S.TodoCardCreate(
        boardId="b1",
        title="Raum buchen",
        dueDate="2026-11-01",
        links=[S.TodoLinkIn(kind="ticket", targetId="t1")],
    )
    asyncio.run(todos.todo_card_create(card))
    assert fake_api.calls == [
        (
            "POST",
            "/todos/cards",
            {
                "boardId": "b1",
                "title": "Raum buchen",
                "dueDate": "2026-11-01",
                "links": [{"kind": "ticket", "targetId": "t1"}],
            },
        )
    ]


def test_todo_card_update_keeps_an_explicit_null(fake_api: _FakeApi) -> None:
    patch = S.TodoCardPatch(version=3, dueDate=None)
    asyncio.run(todos.todo_card_update("c1", patch))
    assert fake_api.calls == [
        ("PATCH", "/todos/cards/c1", {"version": 3, "dueDate": None})
    ]


def test_todo_card_move_to_the_end(fake_api: _FakeApi) -> None:
    asyncio.run(todos.todo_card_move("c1", "col2"))
    assert fake_api.calls == [("POST", "/todos/cards/c1/move", {"columnId": "col2"})]


def test_todo_card_move_between_neighbors(fake_api: _FakeApi) -> None:
    asyncio.run(todos.todo_card_move("c1", "col2", before_id="c3", after_id="c2"))
    assert fake_api.calls[0][2] == {
        "columnId": "col2",
        "beforeId": "c3",
        "afterId": "c2",
    }


def test_todo_comment_without_and_with_mentions(fake_api: _FakeApi) -> None:
    asyncio.run(todos.todo_comment("c1", "Erledigt?"))
    asyncio.run(todos.todo_comment("c1", "@Anna bitte", mentions=["p1"]))
    assert fake_api.calls == [
        ("POST", "/todos/cards/c1/comments", {"body": "Erledigt?", "mentions": []}),
        (
            "POST",
            "/todos/cards/c1/comments",
            {"body": "@Anna bitte", "mentions": ["p1"]},
        ),
    ]


def test_tickets_list_defaults(fake_api: _FakeApi) -> None:
    asyncio.run(tickets.tickets_list())
    assert fake_api.calls == [("GET", "/tickets", {"limit": 50, "offset": 0})]


def test_tickets_list_filters(fake_api: _FakeApi) -> None:
    asyncio.run(
        tickets.tickets_list(
            status=["new", "in_progress"], kind=["bug"], assignee="me", q="40"
        )
    )
    assert fake_api.calls[0][2] == {
        "status": ["new", "in_progress"],
        "kind": ["bug"],
        "assignee": "me",
        "q": "40",
        "limit": 50,
        "offset": 0,
    }


def test_tickets_get_and_note(fake_api: _FakeApi) -> None:
    asyncio.run(tickets.tickets_get("t1"))
    asyncio.run(tickets.tickets_note("t1", "Reproduziert"))
    assert fake_api.calls == [
        ("GET", "/tickets/t1", None),
        ("POST", "/tickets/t1/notes", {"body": "Reproduziert"}),
    ]


def test_tickets_update_unassigns_with_null(fake_api: _FakeApi) -> None:
    asyncio.run(tickets.tickets_update("t1", S.TicketPatch(assigneeId=None)))
    asyncio.run(
        tickets.tickets_update("t1", S.TicketPatch(status="done", completeTodos=True))
    )
    assert fake_api.calls == [
        ("PATCH", "/tickets/t1", {"assigneeId": None}),
        ("PATCH", "/tickets/t1", {"status": "done", "completeTodos": True}),
    ]
