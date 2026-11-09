"""Integration: a cost centre as a link target and the due cards in the calendar feed.

Spec 000552: a budget reader links a cost centre, and each reader of the card sees its
name and path key, a reader without budget read without the url. Spec 000549: an open card
with a due date is in the feed of each assignee, a done card, an Event and a card of
another person are not.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.todos.service import TodoService
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


async def _cost_centre(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with maker() as session:
        key = f"K{uuid.uuid4().hex[:5]}"
        node = Budget(key=key, path_key=f"SP.{key}", name="Bühnentechnik")
        session.add(node)
        await session.commit()
        return node.id


async def test_cost_centre_link_shows_to_every_card_reader(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Spec 000552."""
    ks = await _cost_centre(maker)
    gid, board = await add_gremium(maker, "Kultur")
    admin, _aid = await add_person(maker, "Admin")
    reader, rid = await add_person(maker, "Ada")
    await add_member(maker, gid, rid, "todo.write")

    api.login(Principal(sub=admin.sub, roles=["admin"], permissions=set()))
    with TestClient(api.app) as client:
        hits = _ok(client.get("/api/todos/link-targets", params={"q": "Bühnent", "kind": "budget"}))
        assert [(h["kind"], h["targetId"]) for h in hits] == [("budget", str(ks))]
        card = _ok(
            client.post(
                "/api/todos/cards",
                json={
                    "boardId": str(board),
                    "title": "Haushaltsplan Kultur",
                    "links": [{"kind": "budget", "targetId": str(ks)}],
                },
            ),
            201,
        )
        (own,) = card["links"]
        assert own["url"] == f"/budget?ks={ks}"
        linked = _ok(client.get("/api/todos/linked", params={"kind": "budget", "targetId": ks}))
        assert [c["title"] for c in linked] == ["Haushaltsplan Kultur"]

    api.login(reader)
    with TestClient(api.app) as client:
        (link,) = _ok(client.get(f"/api/todos/cards/{card['id']}"))["links"]
        assert link["accessible"] and not link["granted"]
        assert link["title"] == "Bühnentechnik"
        assert link["detail"]["costCentre"].startswith("SP.K")
        assert link["url"] is None
        other = _ok(
            client.post("/api/todos/cards", json={"boardId": str(board), "title": "Inventur"}),
            201,
        )
        refused = client.post(
            f"/api/todos/cards/{other['id']}/links", json={"kind": "budget", "targetId": str(ks)}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "link_target_not_found"
        assert (
            _ok(client.get("/api/todos/link-targets", params={"q": "Bühnent", "kind": "budget"}))
            == []
        )


async def test_due_cards_of_the_assignee_are_in_the_feed(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Spec 000549."""
    gid, board = await add_gremium(maker, "Kultur")
    person, pid = await add_person(maker, "Ada")
    _other, oid = await add_person(maker, "Bea")
    await add_member(maker, gid, pid, "todo.write")
    await add_member(maker, gid, oid, "todo.write")
    api.login(person)
    with TestClient(api.app) as client:
        detail = _ok(client.get(f"/api/todos/boards/{board}"))
        done = next(c["id"] for c in detail["columns"] if c["isDone"])

        def card(title: str, **kw: Any) -> dict[str, Any]:
            return _ok(
                client.post("/api/todos/cards", json={"boardId": str(board), "title": title, **kw}),
                201,
            )

        mine = card("Raum buchen", dueDate="2026-11-20", assigneeIds=[str(pid)])
        card("Ohne Datum", assigneeIds=[str(pid)])
        card("Für Bea", dueDate="2026-11-21", assigneeIds=[str(oid)])
        card(
            "Fest",
            dueDate="2026-11-22",
            assigneeIds=[str(pid)],
            event={"startsOn": "2026-11-22"},
        )
        finished = card("Erledigt bald", dueDate="2026-11-23", assigneeIds=[str(pid)])
        _ok(client.post(f"/api/todos/cards/{finished['id']}/move", json={"columnId": done}))

    async with maker() as session:
        rows = await TodoService(session).calendar_due_cards(person)
        assert [(c.title, b.name) for c, b in rows] == [("Raum buchen", "Kultur")]
        assert rows[0][0].id == uuid.UUID(mine["id"])

    api.login(person)
    with TestClient(api.app) as client:
        _ok(client.post(f"/api/todos/cards/{mine['id']}/move", json={"columnId": done}))
    async with maker() as session:
        assert await TodoService(session).calendar_due_cards(person) == []
