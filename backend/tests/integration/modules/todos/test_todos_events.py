"""Integration: Events (``Veranstaltung``), a card with event data (specs 000478-000488).

Covers the event data on each board kind, the totals of the linked Anträge and
Buchungen, the decisions, one Event per element, the series and the previous
editions, ``Folgeveranstaltung anlegen``, the one-way conversion, the search with the
archive and the calendar feed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import ApplicationDecision
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear
from app.modules.livevote.models import Meeting, MeetingAgendaItem
from app.modules.todos.service import TodoService
from app.modules.voting.models import Vote
from tests.integration.modules.flow.agenda_support import make_application, seed_agenda_flow
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    add_team_board,
)

pytestmark = pytest.mark.integration

EVENT = {"startsOn": "2026-11-20", "endsOn": "2026-11-21", "place": "Mensa"}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _code(resp: Any, status: int) -> str:
    assert resp.status_code == status, resp.text
    return resp.json()["code"]


def _card(client: TestClient, board_id: Any, title: str, **kw: Any) -> dict[str, Any]:
    return _ok(
        client.post("/api/todos/cards", json={"boardId": str(board_id), "title": title, **kw}),
        201,
    )


def _admin(sub: str) -> Principal:
    return Principal(sub=sub, roles=["admin"], permissions=set())


async def _money(maker: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """An Antrag with a valid decision (500 of 800), a vote of a TOP, and three bookings.

    The booking ``parent`` (300) has the sub-booking ``child`` (100); ``income`` is 75.
    """
    async with maker() as session:
        flow = await seed_agenda_flow(session)
        app = await make_application(session, flow)
        app.amount = Decimal("800.00")
        app.email_confirmed_at = datetime(2026, 10, 1, tzinfo=UTC)
        meeting = Meeting(gremium_id=flow.gremium.id, title="StuPa 3", date=date(2026, 11, 1))
        session.add(meeting)
        await session.flush()
        item = MeetingAgendaItem(meeting_id=meeting.id, title="Erstiparty", position=1)
        session.add(item)
        await session.flush()
        decided_by_vote = Vote(
            eligible_group=str(flow.gremium.id),
            question="Antrag Erstiparty?",
            config={"options": ["yes", "no", "abstain"], "majorityRule": "simple"},
            status="closed",
            result="passed",
            meeting_id=meeting.id,
            application_id=app.id,
            closed_at=datetime(2026, 11, 1, 19, tzinfo=UTC),
        )
        top_vote = Vote(
            eligible_group=str(flow.gremium.id),
            question="Getränke vom Campus-Café?",
            config={"options": ["yes", "no", "abstain"], "majorityRule": "simple"},
            status="closed",
            result="rejected",
            meeting_id=meeting.id,
            agenda_item_id=item.id,
            closed_at=datetime(2026, 11, 1, 20, tzinfo=UTC),
        )
        session.add_all([decided_by_vote, top_vote])
        await session.flush()
        session.add(
            ApplicationDecision(
                application_id=app.id,
                approved_amount=Decimal("500.00"),
                conditions=["Belege bis 31.12."],
                vote_id=decided_by_vote.id,
                decided_at=datetime(2026, 11, 1, 19, tzinfo=UTC),
            )
        )
        node = Budget(key=f"E{uuid.uuid4().hex[:6]}", path_key="", name="Kultur")
        node.path_key = node.key
        session.add(node)
        await session.flush()
        fy = FiscalYear(
            budget_id=node.id, year=2026, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
        )
        session.add(fy)
        await session.flush()

        def booking(amount: str, kind: str = "expense", parent: Any = None) -> BudgetExpense:
            return BudgetExpense(
                budget_id=node.id,
                fiscal_year_id=fy.id,
                amount=Decimal(amount),
                description=f"Buchung {amount}",
                kind=kind,
                parent_expense_id=parent,
            )

        parent = booking("300.00")
        income = booking("75.00", "income")
        session.add_all([parent, income])
        await session.flush()
        child = booking("100.00", parent=parent.id)
        session.add(child)
        await session.commit()
        return {
            "app": app.id,
            "item": item.id,
            "vote": decided_by_vote.id,
            "top_vote": top_vote.id,
            "parent": parent.id,
            "child": child.id,
            "income": income.id,
        }


async def test_event_data_on_each_board_kind(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Spec 000478: a gremium and a team card can be an Event, a personal card cannot."""
    gid, gboard = await add_gremium(maker, "Kultur")
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid, "todo.write")
    team = await add_team_board(maker, "platform.admin")
    me = Principal(sub=person.sub, permissions={"platform.admin"})
    api.login(me)
    with TestClient(api.app) as client:
        personal = _ok(client.get("/api/todos/boards"))
        pboard = next(b["id"] for b in personal if b["kind"] == "personal")
        gcard = _card(client, gboard, "Erstiparty", event=EVENT)
        assert gcard["event"]["startsOn"] == "2026-11-20"
        assert gcard["event"]["place"] == "Mensa"
        assert gcard["eventFacts"]["totals"]["balance"] == "0.00"
        tcard = _card(client, team, "Hackathon", event={"startsOn": "2026-12-01"})
        assert tcard["event"]["endsOn"] is None
        refused = client.post(
            "/api/todos/cards", json={"boardId": pboard, "title": "Party", "event": EVENT}
        )
        assert _code(refused, 422) == "event_personal_board"
        bad = client.post(
            "/api/todos/cards",
            json={"boardId": str(gboard), "title": "X", "event": {"endsOn": "2026-11-20"}},
        )
        assert _code(bad, 422) == "event_dates_invalid"
        todo = _card(client, gboard, "Plakate")
        assert todo["event"] is None and todo["eventFacts"] is None


async def test_totals_decisions_and_one_event_per_element(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Specs 000479, 000481, 000482 and 000489."""
    ids = await _money(maker)
    _gid, board = await add_gremium(maker, "Kultur")
    person, _pid = await add_person(maker, "Ada")
    api.login(_admin(person.sub))
    with TestClient(api.app) as client:
        links = [
            {"kind": "application", "targetId": str(ids["app"])},
            {"kind": "agenda_item", "targetId": str(ids["item"])},
            {"kind": "vote", "targetId": str(ids["vote"])},
            {"kind": "expense", "targetId": str(ids["parent"])},
            {"kind": "expense", "targetId": str(ids["child"])},
            {"kind": "expense", "targetId": str(ids["income"])},
        ]
        party = _card(client, board, "Erstiparty", event=EVENT, links=links)
        totals = party["eventFacts"]["totals"]
        assert totals == {
            "requested": "800.00",
            "approved": "500.00",
            "expenses": "300.00",
            "income": "75.00",
            "balance": "-225.00",
        }
        decisions = party["eventFacts"]["decisions"]
        assert [(d["kind"], d["result"]) for d in decisions] == [
            ("vote", "rejected"),
            ("decision", "passed"),
        ]
        assert decisions[1]["amount"] == "500.00"
        assert decisions[1]["conditions"] == ["Belege bis 31.12."]
        assert decisions[1]["meetingTitle"] == "StuPa 3"

        other = _card(client, board, "Sommerfest", event=EVENT)
        taken = client.post(
            f"/api/todos/cards/{other['id']}/links",
            json={"kind": "expense", "targetId": str(ids["parent"])},
        )
        assert _code(taken, 409) == "event_link_taken"
        plain = _card(client, board, "Plakate", links=[links[3]])
        converted = client.put(f"/api/todos/cards/{plain['id']}/event", json=EVENT)
        assert _code(converted, 409) == "event_link_taken"

        back = _ok(
            client.get("/api/todos/linked", params={"kind": "expense", "targetId": ids["parent"]})
        )
        assert [c["title"] for c in back] == ["Erstiparty", "Plakate"]
        assert back[0]["event"]["place"] == "Mensa" and back[0]["balance"] == "-225.00"
        assert back[1]["event"] is None


async def test_conversion_is_one_way(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    """Spec 000488: a to-do becomes an Event, and the event data cannot go away."""
    gid, board = await add_gremium(maker, "Kultur")
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid, "todo.write")
    api.login(person)
    with TestClient(api.app) as client:
        card = _card(client, board, "Erstiparty")
        assert _code(client.delete(f"/api/todos/cards/{card['id']}/event"), 404) == "not_found"
        event = _ok(client.put(f"/api/todos/cards/{card['id']}/event", json=EVENT))
        assert event["event"]["endsOn"] == "2026-11-21"
        changed = _ok(
            client.put(f"/api/todos/cards/{card['id']}/event", json={"startsOn": "2026-11-22"})
        )
        assert changed["event"]["endsOn"] is None and changed["event"]["place"] is None
        gone = client.delete(f"/api/todos/cards/{card['id']}/event")
        assert _code(gone, 409) == "event_permanent"
        assert _ok(client.get(f"/api/todos/cards/{card['id']}"))["event"] is not None


async def test_series_editions_and_follow_up(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Specs 000483 and 000484: the series, the other editions and the next edition."""
    gid, board = await add_gremium(maker, "Kultur")
    _oid, hidden_board = await add_gremium(maker, "AStA")
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid, "todo.write")
    async with maker() as session:
        service = TodoService(session)
        series = await service.create_series("Erstiparty", _admin(person.sub))
    api.login(person)
    with TestClient(api.app) as client:
        assert _code(client.post("/api/todos/series", json={"name": "erstiparty"}), 409) == (
            "series_exists"
        )
        listed = _ok(client.get("/api/todos/series", params={"q": "ersti"}))
        assert [s["name"] for s in listed] == ["Erstiparty"]
        with_series = {**EVENT, "seriesId": str(series.id)}
        old = _card(
            client, board, "Erstiparty SoSe", event={**with_series, "startsOn": "2026-04-20",
                                                     "endsOn": None},
        )
        _ok(client.post(f"/api/todos/cards/{old['id']}/checklist", json={"text": "DJ"}), 200)
        new = _card(client, board, "Erstiparty WiSe", event=with_series)
        api.login(_admin(person.sub))
        _card(client, hidden_board, "Erstiparty AStA", event=with_series)
        api.login(person)
        detail = _ok(client.get(f"/api/todos/cards/{new['id']}"))
        facts = detail["eventFacts"]
        assert [e["title"] for e in facts["editions"]] == ["Erstiparty SoSe"]
        assert facts["hiddenEditions"] == 1
        assert detail["event"]["seriesName"] == "Erstiparty"

        follow = _ok(client.post(f"/api/todos/cards/{old['id']}/follow-up"), 201)
        assert follow["title"] == "Erstiparty SoSe"
        assert follow["event"]["startsOn"] is None and follow["event"]["endsOn"] is None
        assert follow["event"]["place"] == "Mensa"
        assert follow["event"]["seriesId"] == str(series.id)
        assert [(i["text"], i["done"]) for i in follow["checklistItems"]] == [("DJ", False)]
        assert follow["links"] == [] and follow["assignees"] == []
        assert follow["columnId"] == detail["columns"][0]["id"]
        todo = _card(client, board, "Plakate")
        assert _code(client.post(f"/api/todos/cards/{todo['id']}/follow-up"), 422) == (
            "not_an_event"
        )


async def test_search_finds_archived_events_and_the_feed_lists_them(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Specs 000485 and 000486."""
    gid, board = await add_gremium(maker, "Kultur")
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid, "todo.write")
    api.login(person)
    with TestClient(api.app) as client:
        card = _card(client, board, "Erstiparty Archiv", event=EVENT)
        _card(client, board, "Erstiparty ohne Datum", event={"place": "Mensa"})
        assert client.delete(f"/api/todos/cards/{card['id']}").status_code == 204
        hits = _ok(client.get("/api/search", params={"q": "Erstiparty"}))["hits"]
        events = [h for h in hits if h["kind"] == "event"]
        assert {h["title"] for h in events} == {"Erstiparty Archiv", "Erstiparty ohne Datum"}
        archived = next(h for h in events if h["title"] == "Erstiparty Archiv")
        assert archived["archived"] is True
        assert archived["subtitle"] == "20.11.2026–21.11.2026 · Kultur"
        page = _ok(client.get(f"/api/todos/boards/{board}/archive", params={"events": "true"}))
        assert [c["title"] for c in page["items"]] == ["Erstiparty Archiv"]
        writable = _ok(client.get("/api/todos/events"))
        assert [e["title"] for e in writable] == ["Erstiparty ohne Datum"]
    async with maker() as session:
        rows = await TodoService(session).calendar_events(person)
        assert [card.title for card, _board, _event in rows] == ["Erstiparty Archiv"]
