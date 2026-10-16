"""Integration: a card moves to another board (real Postgres).

Covers the transfer from a gremium board to the personal board and back, the labels
kept by name and dropped without a match, the assignees dropped without membership,
the entry into the done column with ``todo_done`` on a linked ticket, the ETag of both
boards, the errors (404, 409, 422) and a parallel transfer that wins the lock.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.todos.schemas import CardCreate, CardTransfer
from app.modules.todos.service import TodoService
from app.shared.errors import ConflictError
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    add_team_board,
)
from tests.integration.modules.todos.test_todos_lifecycle import _personal

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == code


def _transfer(client: TestClient, card_id: str, board_id: str, **kw: Any) -> Any:
    return client.post(f"/api/todos/cards/{card_id}/transfer", json={"boardId": board_id, **kw})


async def test_a_card_moves_to_the_personal_board_and_back(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    gid, gboard = await add_gremium(maker, "StuPa")
    me, me_id = await add_person(maker, "Mia")
    _other, other_id = await add_person(maker, "Otto")
    await add_member(maker, gid, me_id, "todo.write", "todo.configure")
    await add_member(maker, gid, other_id, "todo.write")
    api.login(Principal(sub=me.sub, permissions={"ticket.manage"}))
    with TestClient(api.app) as client:
        personal = next(b for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "personal")
        pboard = personal["id"]
        gid_s = str(gboard)
        urgent = _ok(
            client.post(
                f"/api/todos/boards/{gid_s}/labels", json={"name": "Eilig", "color": "red"}
            ),
            201,
        )
        later = _ok(
            client.post(
                f"/api/todos/boards/{gid_s}/labels", json={"name": "Später", "color": "blue"}
            ),
            201,
        )
        mine = _ok(
            client.post(
                f"/api/todos/boards/{pboard}/labels", json={"name": "eilig", "color": "red"}
            ),
            201,
        )
        number = _ok(
            client.post("/api/tickets", json={"kind": "bug", "title": "Knopf", "body": "b"}), 201
        )["number"]
        tid = next(
            t["id"] for t in _ok(client.get("/api/tickets"))["items"] if t["number"] == number
        )
        card = _ok(
            client.post(
                "/api/todos/cards",
                json={
                    "boardId": gid_s,
                    "title": "Fix",
                    "assigneeIds": [str(me_id), str(other_id)],
                    "labelIds": [urgent["id"], later["id"]],
                    "links": [{"kind": "ticket", "targetId": tid}],
                },
            ),
            201,
        )
        _ok(client.post(f"/api/todos/cards/{card['id']}/checklist", json={"text": "Eins"}))
        source_etag = client.get(f"/api/todos/boards/{gid_s}").headers["ETag"]
        target_etag = client.get(f"/api/todos/boards/{pboard}").headers["ETag"]
        target = _ok(client.get(f"/api/todos/boards/{pboard}"))
        done = next(c for c in target["columns"] if c["isDone"])
        api.mails.clear()

        moved = _ok(_transfer(client, card["id"], pboard, columnId=done["id"]))
        assert (moved["boardId"], moved["columnId"]) == (pboard, done["id"])
        assert moved["boardName"] == "Meine To-Dos"
        assert [x["name"] for x in moved["labels"]] == ["eilig"]
        assert moved["labelIds"] == [mine["id"]]
        assert [a["principalId"] for a in moved["assignees"]] == [str(me_id)]
        assert moved["completedAt"] is not None
        assert moved["links"][0]["kind"] == "ticket"
        assert moved["checklist"] == {"done": 0, "total": 1}
        assert api.mails == []
        event = next(e for e in reversed(moved["events"]) if e["kind"] == "moved")
        assert event["payload"]["fromBoardName"] == "StuPa"
        assert event["payload"]["toBoardName"] == "Meine To-Dos"
        assert event["payload"]["toColumnName"] == done["name"]
        assert event["payload"]["droppedLabels"] == ["Später"]
        assert event["payload"]["droppedAssignees"] == 1
        ticket = _ok(client.get(f"/api/tickets/{tid}"))
        assert [
            e["payload"]["cardTitle"] for e in ticket["events"] if e["kind"] == "todo_done"
        ] == ["Fix"]
        # Both boards changed: the card left the one and is on the other.
        source = client.get(f"/api/todos/boards/{gid_s}", headers={"If-None-Match": source_etag})
        assert source.status_code == 200
        assert card["id"] not in [c["id"] for c in source.json()["cards"]]
        read = client.get(f"/api/todos/boards/{pboard}", headers={"If-None-Match": target_etag})
        assert read.status_code == 200
        assert card["id"] in [c["id"] for c in read.json()["cards"]]

        # Back to the first column of the gremium board: open again, the label by name.
        back = _ok(_transfer(client, card["id"], gid_s))
        first = _ok(client.get(f"/api/todos/boards/{gid_s}"))["columns"][0]
        assert (back["boardId"], back["columnId"]) == (gid_s, first["id"])
        assert back["completedAt"] is None
        assert back["labelIds"] == [urgent["id"]]
        assert [a["principalId"] for a in back["assignees"]] == [str(me_id)]
        event = back["events"][-1]
        assert event["payload"]["droppedLabels"] == []
        assert event["payload"]["droppedAssignees"] == 0
        # Only the first entry into done wrote to the ticket.
        ticket = _ok(client.get(f"/api/tickets/{tid}"))
        assert len([e for e in ticket["events"] if e["kind"] == "todo_done"]) == 1


async def test_a_done_card_stays_done_in_the_target_done_column(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    me, _me_id = await add_person(maker, "Ada")
    team = await add_team_board(maker, "ticket.manage")
    api.login(Principal(sub=me.sub, permissions={"ticket.manage"}))
    with TestClient(api.app) as client:
        personal = next(b for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "personal")
        pdone = next(
            c
            for c in _ok(client.get(f"/api/todos/boards/{personal['id']}"))["columns"]
            if c["isDone"]
        )
        tdone = next(
            c for c in _ok(client.get(f"/api/todos/boards/{team}"))["columns"] if c["isDone"]
        )
        card = _ok(
            client.post(
                "/api/todos/cards",
                json={"boardId": personal["id"], "title": "Fertig", "columnId": pdone["id"]},
            ),
            201,
        )
        moved = _ok(_transfer(client, card["id"], str(team), columnId=tdone["id"]))
        assert moved["completedAt"] == card["completedAt"]


async def test_the_transfer_errors(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    gid, gboard = await add_gremium(maker)
    me, me_id = await add_person(maker, "Mia")
    other, _ = await add_person(maker, "Otto")
    await add_member(maker, gid, me_id, "todo.write")
    api.login(other)
    with TestClient(api.app) as client:
        foreign = _ok(client.get("/api/todos/boards"))[0]["id"]
        api.login(me)
        personal = _ok(client.get("/api/todos/boards"))[0]
        assert personal["kind"] == "personal"
        pboard = personal["id"]
        card = _ok(client.post("/api/todos/cards", json={"boardId": pboard, "title": "A"}), 201)
        _problem(_transfer(client, card["id"], pboard), 422, "transfer_same_board")
        _problem(_transfer(client, card["id"], foreign), 404, "not_found")
        _problem(_transfer(client, card["id"], str(uuid.uuid4())), 404, "not_found")
        _problem(_transfer(client, str(uuid.uuid4()), str(gboard)), 404, "not_found")
        own_column = _ok(client.get(f"/api/todos/boards/{pboard}"))["columns"][0]["id"]
        _problem(
            _transfer(client, card["id"], str(gboard), columnId=own_column),
            422,
            "column_not_on_board",
        )
        _ok(client.delete(f"/api/todos/cards/{card['id']}"), 204)
        _problem(_transfer(client, card["id"], str(gboard)), 409, "card_archived")
        # Someone without the board cannot move a card onto it.
        api.login(other)
        theirs = _ok(client.post("/api/todos/cards", json={"boardId": foreign, "title": "B"}), 201)
        _problem(_transfer(client, theirs["id"], str(gboard)), 404, "not_found")


async def test_a_parallel_transfer_wins(maker: async_sessionmaker[AsyncSession]) -> None:
    me, me_id = await add_person(maker, "Ada")
    board, _columns = await _personal(maker, me_id)
    team = await add_team_board(maker, "ticket.manage")
    _gid, gboard = await add_gremium(maker)
    principal = Principal(sub=me.sub, permissions={"ticket.manage"})
    async with maker() as session:
        payload = CardCreate.model_validate({"boardId": str(board.id), "title": "A"})
        card_id = (await TodoService(session).create(payload, principal)).id

    async def transfer() -> None:
        async with maker() as session:
            body = CardTransfer.model_validate({"boardId": str(team)})
            await TodoService(session).transfer(card_id, body, principal)

    async with maker() as holder:
        await holder.execute(
            text("SELECT id FROM todo_board WHERE id = ANY(:b) FOR UPDATE"),
            {"b": [board.id, team]},
        )
        task = asyncio.create_task(transfer())
        await asyncio.sleep(0.3)
        assert not task.done()
        column = (
            await holder.execute(
                text("SELECT id FROM todo_column WHERE board_id = :b ORDER BY position LIMIT 1"),
                {"b": gboard},
            )
        ).scalar_one()
        await holder.execute(
            text("UPDATE todo_card SET board_id = :b, column_id = :c WHERE id = :id"),
            {"b": gboard, "c": column, "id": card_id},
        )
        await holder.commit()
    with pytest.raises(ConflictError) as err:
        await asyncio.wait_for(task, 10)
    assert err.value.code == "card_moved"
