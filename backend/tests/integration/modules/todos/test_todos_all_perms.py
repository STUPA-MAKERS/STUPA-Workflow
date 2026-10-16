"""Integration: the global keys ``todo.read_all`` and ``todo.all`` (real Postgres).

A ``todo.read_all`` holder reads every gremium and team board, never a foreign
personal board, gets ``canWrite: false`` and 403 ``todo_write_required`` on every card
write. A ``todo.all`` holder writes there, still cannot configure a board and is no
member (not assignable, not mentionable). The OAuth scope ``read`` carries
``todo.read_all``; the migration grants both keys to the role ``admin``.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.oauth import scope_permissions
from app.modules.auth.principal import Principal
from app.modules.todos.service import TodoService
from app.shared.errors import ForbiddenError
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    add_team_board,
)

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == code


class _World:
    """The boards and the card that a writer prepared for the readers."""

    gremium_id: uuid.UUID
    gboard: str
    team: str
    personal: str
    card: dict[str, Any]
    item: str
    link: str
    comment: str
    label: str
    writer_id: uuid.UUID
    reader: Principal
    reader_id: uuid.UUID
    reader_board: str
    ticket: str


async def _world(api: Api, maker: async_sessionmaker[AsyncSession]) -> _World:
    w = _World()
    w.gremium_id, gboard = await add_gremium(maker, "StuPa")
    w.gboard = str(gboard)
    w.team = str(await add_team_board(maker, "ticket.manage"))
    writer, w.writer_id = await add_person(maker, "Wanda")
    await add_member(maker, w.gremium_id, w.writer_id, "todo.write", "todo.configure")
    reader, w.reader_id = await add_person(maker, "Rita")
    w.reader = Principal(sub=reader.sub, permissions={"todo.read_all"})
    api.login(Principal(sub=writer.sub, permissions={"ticket.manage"}))
    with TestClient(api.app) as client:
        w.personal = next(
            b["id"] for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "personal"
        )
        number = _ok(
            client.post("/api/tickets", json={"kind": "bug", "title": "Knopf", "body": "b"}), 201
        )["number"]
        w.ticket = next(
            t["id"] for t in _ok(client.get("/api/tickets"))["items"] if t["number"] == number
        )
        w.label = _ok(
            client.post(
                f"/api/todos/boards/{w.gboard}/labels", json={"name": "Eilig", "color": "red"}
            ),
            201,
        )["id"]
        card = _ok(
            client.post(
                "/api/todos/cards",
                json={
                    "boardId": w.gboard,
                    "title": "Plakat",
                    "assigneeIds": [str(w.writer_id)],
                    "labelIds": [w.label],
                    "links": [{"kind": "ticket", "targetId": w.ticket}],
                },
            ),
            201,
        )
        _ok(client.post(f"/api/todos/cards/{card['id']}/checklist", json={"text": "Druck"}))
        w.comment = _ok(
            client.post(f"/api/todos/cards/{card['id']}/comments", json={"body": "Los"}), 201
        )["id"]
        w.card = _ok(client.get(f"/api/todos/cards/{card['id']}"))
        w.item = w.card["checklistItems"][0]["id"]
        w.link = w.card["links"][0]["id"]
        _ok(client.post("/api/todos/cards", json={"boardId": w.personal, "title": "Privat"}), 201)
    api.login(w.reader)
    with TestClient(api.app) as client:
        w.reader_board = next(
            b["id"] for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "personal"
        )
    return w


async def test_a_read_all_holder_reads_every_shared_board_but_no_foreign_personal_one(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    w = await _world(api, maker)
    api.login(w.reader)
    with TestClient(api.app) as client:
        boards = {b["id"]: b for b in _ok(client.get("/api/todos/boards"))}
        assert set(boards) == {w.reader_board, w.gboard, w.team}
        assert boards[w.reader_board]["canWrite"] is True
        for shared in (w.gboard, w.team):
            assert boards[shared]["canWrite"] is False
            assert boards[shared]["canConfigure"] is False
        board = _ok(client.get(f"/api/todos/boards/{w.gboard}"))
        assert (board["canWrite"], board["canConfigure"]) == (False, False)
        assert [c["id"] for c in board["cards"]] == [w.card["id"]]
        assert _ok(client.get(f"/api/todos/boards/{w.team}"))["canWrite"] is False
        detail = _ok(client.get(f"/api/todos/cards/{w.card['id']}"))
        assert detail["canWrite"] is False and detail["comments"][0]["body"] == "Los"
        # The members stay the members: the holder is none of them.
        members = _ok(client.get(f"/api/todos/boards/{w.gboard}/members"))
        assert [m["principalId"] for m in members] == [str(w.writer_id)]
        assert _ok(client.get(f"/api/todos/boards/{w.gboard}/archive"))["total"] == 0
        # The cross-board reads see the shared card too.
        linked = _ok(client.get(f"/api/todos/linked?kind=ticket&targetId={w.ticket}"))
        assert [c["id"] for c in linked] == [w.card["id"]]
        targets = _ok(client.get("/api/todos/link-targets?q=Plakat&kind=todo"))
        assert [t["targetId"] for t in targets] == [w.card["id"]]
        # The personal board of the writer stays 404, its card too.
        assert client.get(f"/api/todos/boards/{w.personal}").status_code == 404
        assert _ok(client.get("/api/todos/link-targets?q=Privat&kind=todo")) == []
        # Configuration needs todo.configure.
        _problem(
            client.patch(f"/api/todos/boards/{w.gboard}", json={"name": "X"}),
            403,
            "todo_configure_required",
        )


def _write_calls(w: _World) -> list[tuple[str, str, dict[str, Any] | None]]:
    cid = w.card["id"]
    first = w.card["columns"][1]["id"]
    return [
        ("POST", "/api/todos/cards", {"boardId": w.gboard, "title": "Neu"}),
        ("POST", "/api/todos/cards", {"boardId": w.team, "title": "Neu"}),
        ("PATCH", f"/api/todos/cards/{cid}", {"version": w.card["version"], "title": "Y"}),
        ("POST", f"/api/todos/cards/{cid}/move", {"columnId": first}),
        ("POST", f"/api/todos/cards/{cid}/transfer", {"boardId": w.reader_board}),
        ("DELETE", f"/api/todos/cards/{cid}", None),
        ("POST", f"/api/todos/cards/{cid}/restore", None),
        ("POST", f"/api/todos/cards/{cid}/assignees", {"principalId": str(w.writer_id)}),
        ("DELETE", f"/api/todos/cards/{cid}/assignees/{w.writer_id}", None),
        ("POST", f"/api/todos/cards/{cid}/labels", {"labelId": w.label}),
        ("DELETE", f"/api/todos/cards/{cid}/labels/{w.label}", None),
        ("POST", f"/api/todos/cards/{cid}/checklist", {"text": "Mehr"}),
        ("PATCH", f"/api/todos/cards/{cid}/checklist/{w.item}", {"done": True}),
        ("DELETE", f"/api/todos/cards/{cid}/checklist/{w.item}", None),
        ("POST", f"/api/todos/cards/{cid}/links", {"kind": "ticket", "targetId": w.ticket}),
        ("DELETE", f"/api/todos/cards/{cid}/links/{w.link}", None),
        ("POST", f"/api/todos/cards/{cid}/comments", {"body": "Ich auch"}),
        ("PATCH", f"/api/todos/cards/{cid}/comments/{w.comment}", {"body": "Z"}),
        ("DELETE", f"/api/todos/cards/{cid}/comments/{w.comment}", None),
    ]


_WRITE_ROUTES = [
    "create-gremium",
    "create-team",
    "patch",
    "move",
    "transfer",
    "archive",
    "restore",
    "assign",
    "unassign",
    "label",
    "unlabel",
    "check-add",
    "check-patch",
    "check-delete",
    "link-add",
    "link-remove",
    "comment-add",
    "comment-edit",
    "comment-delete",
]


@pytest.mark.parametrize("route", _WRITE_ROUTES)
async def test_every_card_write_of_a_read_all_holder_is_403(
    api: Api, maker: async_sessionmaker[AsyncSession], route: str
) -> None:
    w = await _world(api, maker)
    method, url, body = dict(zip(_WRITE_ROUTES, _write_calls(w), strict=True))[route]
    api.login(w.reader)
    with TestClient(api.app) as client:
        before = client.get(f"/api/todos/boards/{w.gboard}").headers["ETag"]
        _problem(client.request(method, url, json=body), 403, "todo_write_required")
        assert client.get(f"/api/todos/boards/{w.gboard}").headers["ETag"] == before


async def test_a_transfer_needs_write_on_both_boards(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    w = await _world(api, maker)
    api.login(w.reader)
    with TestClient(api.app) as client:
        own = _ok(
            client.post("/api/todos/cards", json={"boardId": w.reader_board, "title": "Meins"}),
            201,
        )
        _problem(
            client.post(f"/api/todos/cards/{own['id']}/transfer", json={"boardId": w.gboard}),
            403,
            "todo_write_required",
        )
        assert _ok(client.get(f"/api/todos/cards/{own['id']}"))["boardId"] == w.reader_board


async def test_agenda_and_ticket_coupling_need_the_write_right(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    w = await _world(api, maker)
    async with maker() as session:
        with pytest.raises(ForbiddenError) as agenda:
            await TodoService(session).card_for_agenda(
                uuid.UUID(w.card["id"]), w.gremium_id, w.reader
            )
    assert agenda.value.code == "todo_write_required"
    # A ticket manager who only reads the board closes the ticket; the card stays open.
    manager = Principal(sub=w.reader.sub, permissions={"todo.read_all", "ticket.manage"})
    api.login(manager)
    with TestClient(api.app) as client:
        assert _ok(client.get(f"/api/tickets/{w.ticket}"))["openTodoCount"] == 1
        _ok(
            client.patch(f"/api/tickets/{w.ticket}", json={"status": "done", "completeTodos": True})
        )
        assert _ok(client.get(f"/api/todos/cards/{w.card['id']}"))["completedAt"] is None


async def test_an_all_holder_writes_every_shared_board_but_configures_none(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    w = await _world(api, maker)
    holder, holder_id = await add_person(maker, "Alma")
    api.login(Principal(sub=holder.sub, permissions={"todo.all"}))
    with TestClient(api.app) as client:
        boards = {b["id"]: b for b in _ok(client.get("/api/todos/boards"))}
        assert w.personal not in boards
        for shared in (w.gboard, w.team):
            assert (boards[shared]["canWrite"], boards[shared]["canConfigure"]) == (True, False)
        cid = w.card["id"]
        patched = _ok(
            client.patch(f"/api/todos/cards/{cid}", json={"version": 1, "title": "Plakat 2"})
        )
        assert patched["canWrite"] is True
        _ok(client.post(f"/api/todos/cards/{cid}/comments", json={"body": "Erledige ich"}), 201)
        moved = _ok(client.post(f"/api/todos/cards/{cid}/transfer", json={"boardId": w.team}))
        assert moved["boardId"] == w.team
        team_card = _ok(
            client.post("/api/todos/cards", json={"boardId": w.team, "title": "Team"}), 201
        )
        # No member: not assignable, not mentionable.
        _problem(
            client.post(
                f"/api/todos/cards/{team_card['id']}/assignees",
                json={"principalId": str(holder_id)},
            ),
            422,
            "assignee_not_allowed",
        )
        _problem(
            client.post(
                f"/api/todos/cards/{team_card['id']}/comments",
                json={"body": "@Alma", "mentions": [str(holder_id)]},
            ),
            422,
            "mention_not_member",
        )
        # Configuration stays todo.configure.
        _problem(
            client.post(f"/api/todos/boards/{w.gboard}/labels", json={"name": "N", "color": "red"}),
            403,
            "todo_configure_required",
        )
        _problem(
            client.patch(f"/api/todos/boards/{w.team}", json={"name": "X"}),
            403,
            "todo_configure_required",
        )
        # The personal board of the writer stays 404.
        assert client.get(f"/api/todos/boards/{w.personal}").status_code == 404


async def test_the_token_scope_decides_reads_and_writes(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    w = await _world(api, maker)
    read_token = Principal(
        sub=w.reader.sub,
        permissions={"todo.read_all"},
        scope_permissions=scope_permissions(["read"]),
    )
    api.login(read_token)
    with TestClient(api.app) as client:
        boards = _ok(client.get("/api/todos/boards"))
        # The personal board needs todo.write in the scope.
        assert {b["id"] for b in boards} == {w.gboard, w.team}
        assert all(b["canWrite"] is False for b in boards)
        assert _ok(client.get("/api/todos/mine")) == {"items": [], "dueSoonCount": 0}
        _problem(
            client.post("/api/todos/cards", json={"boardId": w.gboard, "title": "Neu"}),
            403,
            "todo_write_required",
        )
    api.login(
        Principal(
            sub=w.reader.sub,
            permissions={"todo.read_all"},
            scope_permissions=scope_permissions(["votes:write"]),
        )
    )
    with TestClient(api.app) as client:
        assert client.get("/api/todos/boards").status_code == 403
        assert client.get(f"/api/todos/boards/{w.gboard}").status_code == 404
    # An admin token with `read` reads the shared boards and writes none of them.
    admin, _ = await add_person(maker, "Ada")
    api.login(
        Principal(sub=admin.sub, roles=["admin"], scope_permissions=scope_permissions(["read"]))
    )
    with TestClient(api.app) as client:
        assert {b["id"] for b in _ok(client.get("/api/todos/boards"))} == {w.gboard, w.team}
        _problem(
            client.post(f"/api/todos/cards/{w.card['id']}/checklist", json={"text": "x"}),
            403,
            "todo_write_required",
        )


def _admin_grants(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT rp.permission FROM role_permission rp "
                    "JOIN role r ON r.id = rp.role_id "
                    "WHERE r.key = 'admin' AND rp.permission LIKE 'todo.%' "
                    "ORDER BY rp.permission"
                )
            ).scalars()
        )


def test_the_migration_grants_both_keys_to_the_admin_role(
    alembic_cfg: Config, engine: Engine
) -> None:
    assert _admin_grants(engine) == ["todo.all", "todo.read_all"]
    command.downgrade(alembic_cfg, "071d20ab0e10")
    try:
        assert _admin_grants(engine) == []
    finally:
        command.upgrade(alembic_cfg, "head")
    assert _admin_grants(engine) == ["todo.all", "todo.read_all"]
