"""Integration: the to-do routes end to end (real Postgres).

Covers the personal board on the first read, the gremium board and its members, the
team board, the card writes with the lexorank moves and the done column, the
optimistic lock, the ETag, labels, checklist, comments with mentions, links and
back-references, the archive, the cross-board reads and the search, and the RBAC.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.todos.models import TodoCard, TodoEvent
from app.modules.todos.service import berlin_today
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


def _card(client: TestClient, board_id: str, title: str, **kw: Any) -> dict[str, Any]:
    return _ok(
        client.post("/api/todos/cards", json={"boardId": board_id, "title": title, **kw}), 201
    )


async def test_the_personal_board_flow(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    me, me_id = await add_person(maker, "Ada")
    api.login(me)
    with TestClient(api.app) as client:
        boards = _ok(client.get("/api/todos/boards"))
        assert [(b["name"], b["kind"]) for b in boards] == [("Meine To-Dos", "personal")]
        # A second read creates nothing new.
        assert len(_ok(client.get("/api/todos/boards"))) == 1
        bid = boards[0]["id"]
        board = _ok(client.get(f"/api/todos/boards/{bid}"))
        names = [c["name"] for c in board["columns"]]
        assert names == ["Offen", "In Arbeit", "Wartet", "Erledigt"]
        first, done = board["columns"][0]["id"], board["columns"][3]["id"]
        a = _card(client, bid, "A", assigneeIds=[str(me_id)], dueDate=str(berlin_today()))
        b = _card(client, bid, "B")
        c = _card(client, bid, "Cee", columnId=done)
        assert c["completedAt"] is not None
        assert a["rank"] < b["rank"]
        assert api.mails == []  # the actor assigned themselves
        # Move C between A and B in the first column: it is open again.
        moved = _ok(
            client.post(
                f"/api/todos/cards/{c['id']}/move",
                json={"columnId": first, "afterId": a["id"], "beforeId": b["id"]},
            )
        )
        assert a["rank"] < moved["rank"] < b["rank"] and moved["completedAt"] is None
        bad = client.post(
            f"/api/todos/cards/{c['id']}/move",
            json={"columnId": first, "afterId": b["id"], "beforeId": a["id"]},
        )
        assert bad.status_code == 422 and bad.json()["code"] == "rank_neighbors_invalid"
        # Optimistic lock.
        patched = _ok(
            client.patch(f"/api/todos/cards/{a['id']}", json={"version": 1, "title": "A2"})
        )
        assert patched["version"] == 2
        stale = client.patch(f"/api/todos/cards/{a['id']}", json={"version": 1, "title": "A3"})
        assert stale.status_code == 409 and stale.json()["code"] == "card_version_conflict"
        # ETag and 304.
        read = client.get(f"/api/todos/boards/{bid}")
        etag = read.headers["ETag"]
        assert (
            client.get(f"/api/todos/boards/{bid}", headers={"If-None-Match": etag}).status_code
            == 304
        )
        _ok(client.post(f"/api/todos/cards/{b['id']}/move", json={"columnId": done}))
        assert (
            client.get(f"/api/todos/boards/{bid}", headers={"If-None-Match": etag}).status_code
            == 200
        )
        # Labels, checklist, comments.
        label = _ok(
            client.post(f"/api/todos/boards/{bid}/labels", json={"name": "Eilig", "color": "red"}),
            201,
        )
        dup = client.post(
            f"/api/todos/boards/{bid}/labels", json={"name": "eilig", "color": "blue"}
        )
        assert dup.status_code == 409
        detail = _ok(
            client.post(f"/api/todos/cards/{a['id']}/labels", json={"labelId": label["id"]})
        )
        assert [x["name"] for x in detail["labels"]] == ["Eilig"]
        detail = _ok(client.post(f"/api/todos/cards/{a['id']}/checklist", json={"text": "Eins"}))
        item = detail["checklistItems"][0]
        detail = _ok(
            client.patch(f"/api/todos/cards/{a['id']}/checklist/{item['id']}", json={"done": True})
        )
        assert detail["checklist"] == {"done": 1, "total": 1}
        note = _ok(
            client.post(
                f"/api/todos/cards/{a['id']}/comments",
                json={"body": "Hi", "mentions": [str(me_id)]},
            ),
            201,
        )
        assert note["isOwn"] is True and note["mentions"][0]["displayName"] == "Ada"
        stranger = client.post(
            f"/api/todos/cards/{a['id']}/comments",
            json={"body": "x", "mentions": [str(uuid.uuid4())]},
        )
        assert stranger.status_code == 422
        # Links to another card, and the back-reference is not offered for todo.
        detail = _ok(
            client.post(
                f"/api/todos/cards/{a['id']}/links", json={"kind": "todo", "targetId": c["id"]}
            )
        )
        assert detail["links"][0]["accessible"] is True and detail["links"][0]["title"] == "Cee"
        again = client.post(
            f"/api/todos/cards/{a['id']}/links", json={"kind": "todo", "targetId": c["id"]}
        )
        assert again.status_code == 409
        hits = _ok(client.get("/api/todos/link-targets?q=Cee&kind=todo"))
        assert c["id"] in {h["targetId"] for h in hits}
        # Mine, archive, restore.
        mine = _ok(client.get("/api/todos/mine"))
        assert [i["title"] for i in mine["items"]] == ["A2"] and mine["dueSoonCount"] == 1
        assert client.delete(f"/api/todos/cards/{c['id']}").status_code == 204
        archive = _ok(client.get(f"/api/todos/boards/{bid}/archive?q=Cee"))
        assert archive["total"] == 1
        assert _ok(client.post(f"/api/todos/cards/{c['id']}/restore"))["archivedAt"] is None
        # Delete a column with its cards.
        wait = board["columns"][2]["id"]
        _ok(client.post(f"/api/todos/cards/{c['id']}/move", json={"columnId": wait}))
        assert client.delete(f"/api/todos/boards/{bid}/columns/{wait}").status_code == 409
        out = _ok(client.delete(f"/api/todos/boards/{bid}/columns/{wait}?moveTo={first}"))
        assert [col["position"] for col in out["columns"]] == [0, 1, 2]
        # The done flag moves.
        out = _ok(client.patch(f"/api/todos/boards/{bid}/columns/{first}", json={"isDone": True}))
        assert [col["isDone"] for col in out["columns"]] == [True, False, False]
        # Search of the palette.
        hits = _ok(client.get("/api/search?q=A2"))
    assert any(
        h["kind"] == "todo" for h in hits.get("hits", hits if isinstance(hits, list) else [])
    )
    async with maker() as session:
        kinds = (
            await session.scalars(
                select(TodoEvent.kind).where(TodoEvent.card_id == uuid.UUID(c["id"]))
            )
        ).all()
    assert "archived" in kinds and "restored" in kinds and "moved" in kinds


async def test_gremium_boards_follow_the_gremium_roles(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    gid, bid = await add_gremium(maker)
    writer, writer_id = await add_person(maker, "Wera")
    lead, lead_id = await add_person(maker, "Lena")
    outsider, _ = await add_person(maker, "Olaf")
    await add_member(maker, gid, writer_id, "todo.write")
    await add_member(maker, gid, lead_id, "todo.write", "todo.configure")
    with TestClient(api.app) as client:
        api.login(outsider)
        assert client.get(f"/api/todos/boards/{bid}").status_code == 404
        api.login(writer)
        summary = [b for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "gremium"]
        assert summary[0]["canConfigure"] is False
        assert client.patch(f"/api/todos/boards/{bid}", json={"name": "X"}).status_code == 403
        members = _ok(client.get(f"/api/todos/boards/{bid}/members"))
        assert [m["displayName"] for m in members] == ["Lena", "Wera"]
        card = _card(client, str(bid), "Plakat", assigneeIds=[str(lead_id)])
        assert [m.recipients for m in api.mails] == [(lead_id,)]
        bad = client.post(
            "/api/todos/cards",
            json={"boardId": str(bid), "title": "x", "assigneeIds": [str(uuid.uuid4())]},
        )
        assert bad.status_code == 422 and bad.json()["code"] == "assignee_not_allowed"
        api.login(lead)
        assert (
            _ok(client.patch(f"/api/todos/boards/{bid}", json={"archiveAfterDays": 7}))[
                "archiveAfterDays"
            ]
            == 7
        )
        mine = _ok(client.get("/api/todos/mine"))
        assert [i["id"] for i in mine["items"]] == [card["id"]]
        # A token without the scope sees nothing.
        api.login(Principal(sub=lead.sub, scope_permissions=frozenset({"vote.cast"})))
        assert client.get("/api/todos/boards").status_code == 403
        assert client.get(f"/api/todos/cards/{card['id']}").status_code == 404


async def test_team_boards_follow_the_permission(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    bid = await add_team_board(maker, "platform.manage")
    me, _ = await add_person(maker, "Ada")
    with TestClient(api.app) as client:
        api.login(me)
        assert client.get(f"/api/todos/boards/{bid}").status_code == 404
        api.login(Principal(sub=me.sub, permissions={"platform.manage"}))
        kinds = [b["kind"] for b in _ok(client.get("/api/todos/boards"))]
        assert kinds == ["personal", "team"]
        assert _ok(client.get(f"/api/todos/boards/{bid}"))["canConfigure"] is True


async def test_ticket_coupling_and_back_references(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    gid, bid = await add_gremium(maker)
    manager, manager_id = await add_person(maker, "Mia")
    await add_member(maker, gid, manager_id, "todo.write")
    staff = Principal(sub=manager.sub, permissions={"ticket.manage"})
    api.login(staff)
    with TestClient(api.app) as client:
        number = _ok(
            client.post("/api/tickets", json={"kind": "bug", "title": "Knopf", "body": "b"}), 201
        )["number"]
        tickets = _ok(client.get("/api/tickets"))["items"]
        tid = next(t["id"] for t in tickets if t["number"] == number)
        card = _card(client, str(bid), "Fix", links=[{"kind": "ticket", "targetId": tid}])
        assert card["primaryLink"]["detail"]["number"] == number
        linked = _ok(client.get(f"/api/todos/linked?kind=ticket&targetId={tid}"))
        assert [c["id"] for c in linked] == [card["id"]]
        assert _ok(client.get(f"/api/tickets/{tid}"))["openTodoCount"] == 1
        done = _ok(
            client.patch(f"/api/tickets/{tid}", json={"status": "done", "completeTodos": True})
        )
        assert done["openTodoCount"] == 0
        event = next(e for e in done["events"] if e["kind"] == "todo_done")
        assert event["payload"]["cardTitle"] == "Fix"
        assert _ok(client.get(f"/api/todos/cards/{card['id']}"))["completedAt"] is not None
        # A manager who cannot read the board sees no title.
        other, _ = await add_person(maker, "Otto")
        api.login(Principal(sub=other.sub, permissions={"ticket.manage"}))
        event = next(
            e for e in _ok(client.get(f"/api/tickets/{tid}"))["events"] if e["kind"] == "todo_done"
        )
        assert event["payload"]["cardTitle"] is None


async def test_a_card_becomes_an_agenda_item(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    from datetime import date

    from app.modules.livevote.models import Meeting

    gid, bid = await add_gremium(maker)
    admin, _ = await add_person(maker, "Admin")
    api.login(Principal(sub=admin.sub, roles=["admin"]))
    async with maker() as session:
        meeting = Meeting(
            gremium_id=gid, title="GV", date=date.today() + timedelta(days=3), status="planned"
        )
        session.add(meeting)
        await session.commit()
    with TestClient(api.app) as client:
        card = _card(client, str(bid), "Haushalt")
        items = _ok(client.post(f"/api/meetings/{meeting.id}/agenda", json={"todoId": card["id"]}))
        assert [(i["title"], i["todoId"]) for i in items] == [("Haushalt", card["id"])]
        again = client.post(f"/api/meetings/{meeting.id}/agenda", json={"todoId": card["id"]})
        assert again.status_code == 409 and again.json()["code"] == "todo_already_on_agenda"
        detail = _ok(client.get(f"/api/todos/cards/{card['id']}"))
        assert detail["links"][0]["kind"] == "agenda_item"
        assert detail["links"][0]["detail"]["position"] == 1
        linked = _ok(client.get(f"/api/todos/linked?kind=meeting&targetId={meeting.id}"))
        assert linked == []  # the card links the item, not the meeting
        personal = next(b for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "personal")
        mine = _card(client, personal["id"], "Privat")
        wrong = client.post(f"/api/meetings/{meeting.id}/agenda", json={"todoId": mine["id"]})
        assert wrong.status_code == 422 and wrong.json()["code"] == "todo_wrong_board"
    async with maker() as session:
        row = await session.get(TodoCard, uuid.UUID(card["id"]))
        assert row is not None


async def test_votes_gremien_invoices_and_bookings_as_link_targets(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    from datetime import date
    from decimal import Decimal

    from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear, Invoice
    from app.modules.voting.models import Vote

    gid, bid = await add_gremium(maker, "Finanzer")
    lead, lead_id = await add_person(maker, "Lena")
    await add_member(maker, gid, lead_id, "todo.write", "vote.manage")
    async with maker() as session:
        node = Budget(key=f"T{uuid.uuid4().hex[:6]}", path_key="", name="Kultur")
        node.path_key = node.key
        session.add(node)
        await session.flush()
        fy = FiscalYear(
            budget_id=node.id, year=2026, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        invoice = Invoice(number="RE-77", supplier="Druckhaus", gross_amount=Decimal("119.00"))
        session.add_all([fy, invoice])
        await session.flush()
        booking = BudgetExpense(
            budget_id=node.id,
            fiscal_year_id=fy.id,
            amount=Decimal("42.50"),
            description="Plakate Sommerfest",
            invoice_id=invoice.id,
        )
        vote = Vote(
            eligible_group=str(gid),
            question="Sommerfest Plakate?",
            config={"options": ["yes", "no", "abstain"], "majorityRule": "simple"},
            status="closed",
            result="passed",
        )
        session.add_all([booking, vote])
        await session.commit()
        ids = {"vote": vote.id, "gremium": gid, "invoice": invoice.id, "expense": booking.id}

    booker = Principal(sub=lead.sub, permissions={"budget.view"})
    api.login(booker)
    with TestClient(api.app) as client:
        links = [{"kind": k, "targetId": str(v)} for k, v in ids.items()]
        card = _card(client, str(bid), "Plakate", links=links)
        detail = _ok(client.get(f"/api/todos/cards/{card['id']}"))
        by_kind = {link["kind"]: link for link in detail["links"]}
        assert by_kind["vote"]["title"] == "Sommerfest Plakate?"
        assert by_kind["vote"]["url"] == f"/voting/{ids['vote']}"
        assert by_kind["vote"]["detail"]["voteResult"] == "passed"
        assert by_kind["gremium"]["title"] == "Finanzer"
        assert by_kind["gremium"]["url"] == f"/gremien/{gid}"
        assert by_kind["invoice"]["title"] == "RE-77"
        assert by_kind["invoice"]["detail"]["amount"] == "119.00"
        assert by_kind["expense"]["detail"]["costCentre"] == node.path_key
        assert by_kind["expense"]["url"] == f"/expenses?id={ids['expense']}"
        for kind, target in ids.items():
            linked = _ok(client.get(f"/api/todos/linked?kind={kind}&targetId={target}"))
            assert [c["id"] for c in linked] == [card["id"]]
        found = _ok(client.get("/api/todos/link-targets?q=Plakate"))
        assert {(h["kind"], h["targetId"]) for h in found} >= {
            ("vote", str(ids["vote"])),
            ("expense", str(ids["expense"])),
        }
        assert {h["kind"] for h in _ok(client.get("/api/todos/link-targets?q=RE-77"))} >= {
            "invoice"
        }
        assert ("gremium", str(gid)) in {
            (h["kind"], h["targetId"])
            for h in _ok(client.get("/api/todos/link-targets?q=Finanzer&kind=gremium"))
        }

        # Without a budget permission the invoice and the booking redact, and the picker
        # offers neither.
        api.login(lead)
        by_kind = {
            link["kind"]: link
            for link in _ok(client.get(f"/api/todos/cards/{card['id']}"))["links"]
        }
        assert by_kind["invoice"]["accessible"] is False and by_kind["invoice"]["title"] is None
        assert by_kind["expense"]["accessible"] is False and by_kind["expense"]["url"] is None
        assert by_kind["vote"]["accessible"] is True and by_kind["gremium"]["accessible"] is True
        assert _ok(client.get("/api/todos/link-targets?q=RE-77&kind=invoice")) == []
        bad = client.post(
            f"/api/todos/cards/{card['id']}/links",
            json={"kind": "invoice", "targetId": str(uuid.uuid4())},
        )
        assert bad.status_code == 422

    # A delete of the target removes the link (ON DELETE CASCADE).
    async with maker() as session:
        await session.delete(await session.get(Vote, ids["vote"]))
        await session.commit()
    api.login(booker)
    try:
        with TestClient(api.app) as client:
            kinds = {
                link["kind"] for link in _ok(client.get(f"/api/todos/cards/{card['id']}"))["links"]
            }
            assert kinds == {"gremium", "invoice", "expense"}
    finally:
        # The budget rows are no part of the to-do cleanup; other tests count invoices.
        async with maker() as session:
            await session.delete(await session.get(BudgetExpense, ids["expense"]))
            await session.delete(await session.get(Invoice, ids["invoice"]))
            await session.flush()
            await session.delete(await session.get(FiscalYear, fy.id))
            await session.flush()
            await session.delete(await session.get(Budget, node.id))
            await session.commit()
