"""Integration: ``GET /api/todos/all/boards`` and the transfer to a place (real Postgres).

Covers the meta-board "Alle": every readable board, the personal one first (the call
creates it), then the gremium boards by name, then team; every live card (other
people's too, done ones in, archived ones out) with ``cardCount`` per column; the read
scope (a board without the right is left out, a foreign personal board too, a
``todo.read_all`` holder gets the shared boards with ``canWrite`` false); the ETag
and 304; the scope gate of a token. Then a transfer between two neighbors of the
target column, and the 422 for a neighbor outside it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    add_team_board,
)

pytestmark = pytest.mark.integration

ALL = "/api/todos/all/boards"


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _card(client: TestClient, board_id: str, title: str, **kw: Any) -> dict[str, Any]:
    return _ok(
        client.post("/api/todos/cards", json={"boardId": board_id, "title": title, **kw}), 201
    )


async def test_all_boards_lists_every_readable_board_with_all_live_cards(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    stupa, stupa_board = await add_gremium(maker, "StuPa")
    asta, asta_board = await add_gremium(maker, "AStA")
    _fsi, fsi_board = await add_gremium(maker, "FSI")
    team_board = await add_team_board(maker, "ticket.manage")
    me, me_id = await add_person(maker, "Mara")
    other, other_id = await add_person(maker, "Olaf")
    reader, _reader_id = await add_person(maker, "Rita")
    for gid in (stupa, asta):
        await add_member(maker, gid, me_id, "todo.write")
    await add_member(maker, stupa, other_id, "todo.write")
    viewer = Principal(sub=me.sub, email=me.email, permissions={"ticket.manage"})
    with TestClient(api.app) as client:
        api.login(other)
        foreign = _ok(client.get(ALL))
        assert [b["kind"] for b in foreign] == ["personal", "gremium"]
        _card(client, foreign[0]["id"], "Fremd privat")
        theirs = _card(client, str(stupa_board), "Von Olaf", assigneeIds=[str(other_id)])

        api.login(viewer)
        rows = _ok(client.get(ALL))
        assert [(b["name"], b["kind"]) for b in rows] == [
            ("Meine To-Dos", "personal"),
            ("AStA", "gremium"),
            ("StuPa", "gremium"),
            ("Plattform", "team"),
        ]
        assert all(b["canWrite"] for b in rows)
        assert str(fsi_board) not in {b["id"] for b in rows}
        assert foreign[0]["id"] not in {b["id"] for b in rows}
        personal = rows[0]["id"]
        columns = rows[2]["columns"]
        done = next(c for c in columns if c["isDone"])
        _card(client, personal, "Privat")
        _card(client, str(stupa_board), "Niemand")
        _card(client, str(stupa_board), "Fertig", columnId=done["id"])
        gone = _card(client, str(stupa_board), "Weg")
        _ok(client.delete(f"/api/todos/cards/{gone['id']}"), 204)

        etag = client.get(ALL).headers["ETag"]
        assert client.get(ALL, headers={"If-None-Match": etag}).status_code == 304
        _card(client, str(team_board), "Ticket")
        # A write changes the tag.
        assert client.get(ALL, headers={"If-None-Match": etag}).status_code == 200
        rows = _ok(client.get(ALL))
        assert [c["title"] for c in rows[0]["cards"]] == ["Privat"]
        assert rows[1]["cards"] == [] and [c["cardCount"] for c in rows[1]["columns"]] == [
            0,
            0,
            0,
            0,
        ]
        st = rows[2]
        assert st["id"] == str(stupa_board)
        assert [c["id"] for c in st["columns"]] == [c["id"] for c in columns]
        assert [c["title"] for c in st["cards"]] == ["Von Olaf", "Niemand", "Fertig"]
        assert st["cards"][0]["id"] == theirs["id"]
        counts = {c["name"]: c["cardCount"] for c in st["columns"]}
        assert counts == {"Offen": 2, "In Arbeit": 0, "Wartet": 0, "Erledigt": 1}
        assert [c["title"] for c in rows[3]["cards"]] == ["Ticket"]

        # A todo.read_all holder reads every shared board, writes none, and sees no
        # foreign personal board.
        api.login(Principal(sub=reader.sub, permissions={"todo.read_all"}))
        read = _ok(client.get(ALL))
        assert [b["name"] for b in read] == ["Meine To-Dos", "AStA", "FSI", "StuPa", "Plattform"]
        assert [b["canWrite"] for b in read] == [True, False, False, False, False]
        assert personal not in {b["id"] for b in read}
        assert [c["title"] for c in read[3]["cards"]] == ["Von Olaf", "Niemand", "Fertig"]

        api.login(Principal(sub=me.sub, scope_permissions=frozenset({"vote.cast"})))
        denied = client.get(ALL)
        assert denied.status_code == 403
        assert denied.headers["content-type"].startswith("application/problem+json")


async def test_a_transfer_lands_between_two_neighbors(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    gid, gboard = await add_gremium(maker, "StuPa")
    me, me_id = await add_person(maker, "Mia")
    await add_member(maker, gid, me_id, "todo.write")
    api.login(me)
    with TestClient(api.app) as client:
        rows = _ok(client.get(ALL))
        personal = rows[0]["id"]
        target = rows[1]["columns"][0]["id"]
        first = _card(client, str(gboard), "Eins")
        second = _card(client, str(gboard), "Zwei")
        other_column = rows[1]["columns"][1]["id"]
        elsewhere = _card(client, str(gboard), "Andere Spalte", columnId=other_column)
        card = _card(client, personal, "Neu")

        bad = client.post(
            f"/api/todos/cards/{card['id']}/transfer",
            json={"boardId": str(gboard), "columnId": target, "afterId": elsewhere["id"]},
        )
        assert bad.status_code == 422, bad.text
        assert bad.headers["content-type"].startswith("application/problem+json")
        assert bad.json()["code"] == "rank_neighbors_invalid"
        assert _ok(client.get(f"/api/todos/cards/{card['id']}"))["boardId"] == personal

        moved = _ok(
            client.post(
                f"/api/todos/cards/{card['id']}/transfer",
                json={
                    "boardId": str(gboard),
                    "columnId": target,
                    "afterId": first["id"],
                    "beforeId": second["id"],
                },
            )
        )
        assert moved["boardId"] == str(gboard) and moved["columnId"] == target
        board = _ok(client.get(f"/api/todos/boards/{gboard}"))
        in_target = [c["title"] for c in board["cards"] if c["columnId"] == target]
        assert in_target == ["Eins", "Neu", "Zwei"]
        assert [c["id"] for c in _ok(client.get(ALL))[0]["cards"]] == []
