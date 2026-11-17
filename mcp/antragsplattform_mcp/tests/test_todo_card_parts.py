"""§ 001200: the checklist (subtasks), the card fields and the board setup have tools.

Each tool sends exactly one request with the wire keys of the backend.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, todos


class _FakeApi:
    """Record each request and answer with an empty object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def _record(self, method: str, path: str, kw: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, path, kw.get("json", kw.get("params"))))
        return {}

    async def get(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("GET", path, kw)

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("POST", path, kw)

    async def put(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("PUT", path, kw)

    async def patch(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("PATCH", path, kw)

    async def delete(self, path: str, **kw: Any) -> dict[str, Any]:
        return await self._record("DELETE", path, kw)


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_checklist_tools_add_tick_and_remove_a_subtask(fake_api: _FakeApi) -> None:
    """§ 001200: an agent adds, ticks, renames, moves and removes a subtask of a card."""
    asyncio.run(todos.todo_checklist_add("c1", "Raum buchen"))
    asyncio.run(todos.todo_checklist_update("c1", "i1", done=True))
    asyncio.run(todos.todo_checklist_update("c1", "i1", text="Raum A buchen", position=0))
    asyncio.run(todos.todo_checklist_remove("c1", "i1"))
    assert fake_api.calls == [
        ("POST", "/todos/cards/c1/checklist", {"text": "Raum buchen"}),
        ("PATCH", "/todos/cards/c1/checklist/i1", {"done": True}),
        ("PATCH", "/todos/cards/c1/checklist/i1", {"text": "Raum A buchen", "position": 0}),
        ("DELETE", "/todos/cards/c1/checklist/i1", None),
    ]


def test_card_create_carries_the_checklist(fake_api: _FakeApi) -> None:
    """§ 001200: a new card takes its first subtasks in the create."""
    card = S.TodoCardCreate(boardId="b1", title="Fest", checklist=["Bänke", "Grill"])
    asyncio.run(todos.todo_card_create(card))
    assert fake_api.calls == [
        (
            "POST",
            "/todos/cards",
            {"boardId": "b1", "title": "Fest", "checklist": ["Bänke", "Grill"]},
        )
    ]


def test_card_field_tools(fake_api: _FakeApi) -> None:
    """§ 001200: assignees, labels and links change after the create."""
    asyncio.run(todos.todo_card_assignee_add("c1", "p1"))
    asyncio.run(todos.todo_card_assignee_remove("c1", "p1"))
    asyncio.run(todos.todo_card_label_add("c1", "l1"))
    asyncio.run(todos.todo_card_label_remove("c1", "l1"))
    asyncio.run(todos.todo_card_link_add("c1", S.TodoLinkIn(kind="ticket", targetId="t1")))
    asyncio.run(todos.todo_card_link_remove("c1", "k1"))
    assert fake_api.calls == [
        ("POST", "/todos/cards/c1/assignees", {"principalId": "p1"}),
        ("DELETE", "/todos/cards/c1/assignees/p1", None),
        ("POST", "/todos/cards/c1/labels", {"labelId": "l1"}),
        ("DELETE", "/todos/cards/c1/labels/l1", None),
        ("POST", "/todos/cards/c1/links", {"kind": "ticket", "targetId": "t1"}),
        ("DELETE", "/todos/cards/c1/links/k1", None),
    ]


def test_board_setup_tools(fake_api: _FakeApi) -> None:
    """§ 001200: columns and labels of a board are set up through tools."""
    asyncio.run(todos.todo_column_add("b1", "Später"))
    asyncio.run(todos.todo_column_update("b1", "col1", is_done=True))
    asyncio.run(todos.todo_columns_order("b1", ["col2", "col1"]))
    asyncio.run(todos.todo_column_delete("b1", "col1", move_to="col2"))
    asyncio.run(todos.todo_label_add("b1", "Dringend", "red"))
    asyncio.run(todos.todo_board_update("b1", name="Plattform"))
    assert fake_api.calls == [
        ("POST", "/todos/boards/b1/columns", {"name": "Später"}),
        ("PATCH", "/todos/boards/b1/columns/col1", {"isDone": True}),
        ("PUT", "/todos/boards/b1/columns/order", {"columnIds": ["col2", "col1"]}),
        ("DELETE", "/todos/boards/b1/columns/col1", {"moveTo": "col2"}),
        ("POST", "/todos/boards/b1/labels", {"name": "Dringend", "color": "red"}),
        ("PATCH", "/todos/boards/b1", {"name": "Plattform"}),
    ]
