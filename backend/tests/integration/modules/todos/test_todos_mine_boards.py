"""Integration: ``GET /api/todos/mine/boards``, the rows under "Meine To-Dos" (real Postgres).

Covers the grouping by board with all columns, the filter to the caller's live cards
(done ones in, archived ones and other people's cards out), the personal board left
out, the read scope (a board that the caller can no longer read is left out although
a card still names the caller), the move through the normal move route, the ETag and
304, and the scope gate of a token.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import GremiumMembership
from app.modules.auth.principal import Principal
from app.modules.todos.models import TodoAssignee
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    add_team_board,
)

pytestmark = pytest.mark.integration

ROWS = "/api/todos/mine/boards"


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _card(client: TestClient, board_id: str, title: str, **kw: Any) -> dict[str, Any]:
    return _ok(
        client.post("/api/todos/cards", json={"boardId": board_id, "title": title, **kw}), 201
    )


async def test_the_rows_hold_only_my_live_cards_on_boards_i_read(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    stupa, stupa_board = await add_gremium(maker, "StuPa")
    asta, asta_board = await add_gremium(maker, "AStA")
    _fsi, fsi_board = await add_gremium(maker, "FSI")
    team_board = await add_team_board(maker, "ticket.manage")
    me, me_id = await add_person(maker, "Mara")
    other, other_id = await add_person(maker, "Olaf")
    for gid in (stupa, asta):
        await add_member(maker, gid, me_id, "todo.write")
        await add_member(maker, gid, other_id, "todo.write")
    viewer = Principal(sub=me.sub, email=me.email, permissions={"ticket.manage"})
    with TestClient(api.app) as client:
        api.login(viewer)
        assert _ok(client.get(ROWS)) == []
        boards = _ok(client.get("/api/todos/boards"))
        personal = next(b for b in boards if b["kind"] == "personal")
        _card(client, personal["id"], "Privat", assigneeIds=[str(me_id)])
        columns = _ok(client.get(f"/api/todos/boards/{stupa_board}"))["columns"]
        done = next(c for c in columns if c["isDone"])
        first = _card(client, str(stupa_board), "Plakat", assigneeIds=[str(me_id)])
        second = _card(client, str(stupa_board), "Raum", assigneeIds=[str(me_id), str(other_id)])
        _card(client, str(stupa_board), "Fremd", assigneeIds=[str(other_id)])
        _card(client, str(stupa_board), "Niemand")
        _card(client, str(stupa_board), "Fertig", columnId=done["id"], assigneeIds=[str(me_id)])
        gone = _card(client, str(stupa_board), "Weg", assigneeIds=[str(me_id)])
        _ok(client.delete(f"/api/todos/cards/{gone['id']}"), 204)
        asta_card = _card(client, str(asta_board), "Haushalt", assigneeIds=[str(me_id)])
        ticket = _card(client, str(team_board), "Ticket")
        # The team members come from the roles in the database; write the assignee there.
        async with maker() as session:
            session.add(TodoAssignee(card_id=uuid.UUID(ticket["id"]), principal_id=me_id))
            await session.commit()

        rows = _ok(client.get(ROWS))
        assert [(b["name"], b["kind"]) for b in rows] == [
            ("AStA", "gremium"),
            ("StuPa", "gremium"),
            ("Plattform", "team"),
        ]
        st = rows[1]
        assert st["id"] == str(stupa_board) and st["canWrite"] is True
        assert [c["id"] for c in st["columns"]] == [c["id"] for c in columns]
        assert [c["title"] for c in st["cards"]] == ["Plakat", "Raum", "Fertig"]
        counts = {c["name"]: c["cardCount"] for c in st["columns"]}
        assert counts == {"Offen": 2, "In Arbeit": 0, "Wartet": 0, "Erledigt": 1}
        assert [c["id"] for c in rows[0]["cards"]] == [asta_card["id"]]
        assert [c["title"] for c in rows[2]["cards"]] == ["Ticket"]

        # A move through the normal route reorders the row on the source board.
        _ok(
            client.post(
                f"/api/todos/cards/{second['id']}/move",
                json={"columnId": columns[0]["id"], "beforeId": first["id"]},
            )
        )
        st = _ok(client.get(ROWS))[1]
        assert [c["title"] for c in st["cards"]] == ["Raum", "Plakat", "Fertig"]

        etag = client.get(ROWS).headers["ETag"]
        assert client.get(ROWS, headers={"If-None-Match": etag}).status_code == 304

        # The other person sees only their own cards.
        api.login(other)
        theirs = _ok(client.get(ROWS))
        assert [b["name"] for b in theirs] == ["StuPa"]
        assert [c["title"] for c in theirs[0]["cards"]] == ["Raum", "Fremd"]
        # The ETag follows the viewer: my tag does not match the rows of another person.
        assert client.get(ROWS, headers={"If-None-Match": etag}).status_code == 200

    # Without the membership the AStA board is gone, although the card still names me;
    # without the permission the team board is gone too.
    async with maker() as session:
        await session.execute(
            delete(GremiumMembership).where(
                GremiumMembership.gremium_id == asta, GremiumMembership.principal_id == me_id
            )
        )
        await session.commit()
    with TestClient(api.app) as client:
        api.login(me)
        rows = _ok(client.get(ROWS))
        assert [b["name"] for b in rows] == ["StuPa"]
        assert all(c["boardId"] == str(stupa_board) for c in rows[0]["cards"])
        assert str(fsi_board) not in {b["id"] for b in rows}
        api.login(Principal(sub=me.sub, scope_permissions=frozenset({"vote.cast"})))
        denied = client.get(ROWS)
        assert denied.status_code == 403
        assert denied.headers["content-type"].startswith("application/problem+json")
