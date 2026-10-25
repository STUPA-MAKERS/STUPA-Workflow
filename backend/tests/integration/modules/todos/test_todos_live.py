"""Integration: the board pings over ``WS /api/ws/todos`` (real Postgres, in-memory broker).

Covers the subscribe that keeps only the readable boards, the ping after a create,
a move, an archive and a board change, the tile read that a ping names (404 when
archived), the two pings of a transfer, the principal that every subscribe resolves
again (a lost right drops the board, a lost session closes 4401), and the socket
without a session.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketDisconnect

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.todos.router import get_todo_broker
from app.modules.todos.socket import (
    get_todo_ws_broker,
    get_todo_ws_principal,
    get_todo_ws_resolver,
)
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _live(api: Api, principal: Principal) -> list[Principal | None]:
    """Wire the in-memory broker; the returned list is what the next subscribe resolves."""
    broker = InMemoryBroker()
    current: list[Principal | None] = [principal]
    api.login(principal)
    api.app.dependency_overrides[get_todo_broker] = lambda: broker
    api.app.dependency_overrides[get_todo_ws_broker] = lambda: broker
    api.app.dependency_overrides[get_todo_ws_principal] = lambda: principal

    async def _again() -> Principal | None:
        return current[0]

    api.app.dependency_overrides[get_todo_ws_resolver] = lambda: _again
    return current


def _personal(client: TestClient) -> str:
    return next(b["id"] for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "personal")


async def test_pings_reach_the_readable_boards_only(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Send the pings of the readable boards only.

    A write on the unreadable board never reaches this socket, while a write on the readable
    one does. A read changes nothing and sends nothing, so the next ping is the next write.
    """
    gid, gboard = await add_gremium(maker, "StuPa")
    _hidden_gid, hidden = await add_gremium(maker, "AStA")
    me, me_id = await add_person(maker, "Mia")
    await add_member(maker, gid, me_id, "todo.write", "todo.configure")
    _live(api, Principal(sub=me.sub))
    board = str(gboard)
    with TestClient(api.app) as client, client.websocket_connect("/api/ws/todos") as ws:
        ws.send_json({"type": "subscribe", "boardIds": [board, str(hidden), str(uuid.uuid4())]})
        assert ws.receive_json() == {"type": "subscribed", "boardIds": [board]}
        card = _ok(client.post("/api/todos/cards", json={"boardId": board, "title": "Plakat"}), 201)
        ping = {"type": "card", "boardId": board, "cardId": card["id"]}
        assert ws.receive_json() == ping
        done = next(c for c in card["columns"] if c["isDone"])
        _ok(client.post(f"/api/todos/cards/{card['id']}/move", json={"columnId": done["id"]}))
        assert ws.receive_json() == ping
        tile = _ok(client.get(f"/api/todos/cards/{card['id']}/tile"))
        assert tile["columnId"] == done["id"] and tile["completedAt"] is not None
        _ok(client.patch(f"/api/todos/boards/{board}", json={"name": "StuPa-Board"}))
        assert ws.receive_json() == {"type": "board", "boardId": board}
        _ok(client.delete(f"/api/todos/cards/{card['id']}"), 204)
        assert ws.receive_json() == {**ping, "type": "card_removed"}
        assert client.get(f"/api/todos/cards/{card['id']}/tile").status_code == 404
        _ok(client.get(f"/api/todos/boards/{board}"))
        _ok(client.post(f"/api/todos/boards/{board}/columns", json={"name": "Später"}), 201)
        assert ws.receive_json() == {"type": "board", "boardId": board}


async def test_a_transfer_pings_both_boards(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    gid, gboard = await add_gremium(maker, "StuPa")
    me, me_id = await add_person(maker, "Mia")
    await add_member(maker, gid, me_id, "todo.write")
    _live(api, Principal(sub=me.sub))
    board = str(gboard)
    with TestClient(api.app) as client:
        personal = _personal(client)
        card = _ok(
            client.post("/api/todos/cards", json={"boardId": personal, "title": "Flyer"}), 201
        )
        with client.websocket_connect("/api/ws/todos") as ws:
            ws.send_json({"type": "subscribe", "boardIds": [board, personal]})
            assert ws.receive_json()["boardIds"] == [board, personal]
            moved = client.post(f"/api/todos/cards/{card['id']}/transfer", json={"boardId": board})
            _ok(moved)
            pings = [ws.receive_json(), ws.receive_json()]
    assert pings == [
        {"type": "card_removed", "boardId": personal, "cardId": card["id"]},
        {"type": "card", "boardId": board, "cardId": card["id"]},
    ]


async def test_every_subscribe_resolves_the_session_again(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Resolve the session again at every subscribe.

    When the admin role is gone, the next subscribe no longer keeps the board. When the
    session is gone, the socket closes with 4401.
    """
    _gid, gboard = await add_gremium(maker, "StuPa")
    admin, _admin_id = await add_person(maker, "Ada")
    current = _live(api, Principal(sub=admin.sub, roles=["admin"]))
    board = str(gboard)
    with TestClient(api.app) as client, client.websocket_connect("/api/ws/todos") as ws:
        ws.send_json({"type": "subscribe", "boardIds": [board]})
        assert ws.receive_json() == {"type": "subscribed", "boardIds": [board]}
        current[0] = Principal(sub=admin.sub)
        ws.send_json({"type": "subscribe", "boardIds": [board]})
        assert ws.receive_json() == {"type": "subscribed", "boardIds": []}
        current[0] = None
        ws.send_json({"type": "subscribe", "boardIds": [board]})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


async def test_the_socket_without_a_session_closes(api: Api) -> None:
    with (
        TestClient(api.app) as client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/api/ws/todos"),
    ):
        pass
    assert exc.value.code == 4401
