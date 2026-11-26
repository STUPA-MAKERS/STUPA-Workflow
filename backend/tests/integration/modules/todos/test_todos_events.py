"""Integration: Veranstaltungen, an element of its own with a team (003022-003034).

Covers the create, the rights of the team, the fields and their checks, the status, the
version, the totals of the linked Anträge and Buchungen, the decisions, one Event per
element, the series and the other editions, the segments, the search, the calendar, the
picker of a Buchung, the export, the webhook events and the card without event data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import ApplicationDecision
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget, BudgetExpense, FiscalYear
from app.modules.flow.models import State
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.voting.models import Vote
from app.modules.webhooks.models import Webhook, WebhookDelivery
from tests.integration.modules.flow.agenda_support import make_application, seed_agenda_flow
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    team_of,
)

pytestmark = pytest.mark.integration

EVENT = {"startsOn": "2026-11-20", "endsOn": "2026-11-21", "place": "Mensa"}
TODAY = date.today()


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _code(resp: Any, status: int) -> str:
    assert resp.status_code == status, resp.text
    return resp.json()["code"]


def _event(client: TestClient, team: Any, title: str, **kw: Any) -> dict[str, Any]:
    return _ok(client.post("/api/events", json={"teamId": str(team), "title": title, **kw}), 201)


async def _sub_team(maker: async_sessionmaker[AsyncSession], parent: uuid.UUID) -> uuid.UUID:
    async with maker() as session:
        found = await session.execute(
            text("INSERT INTO team (name, parent_id) VALUES ('Unterteam', :p) RETURNING id"),
            {"p": parent},
        )
        team = found.scalar_one()
        await session.commit()
        return team


def _admin(sub: str) -> Principal:
    return Principal(sub=sub, roles=["admin"], permissions=set())


async def _money(maker: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """An approved Antrag with a decision (500 of 800), a vote of a TOP, and three bookings.

    The Antrag sits in the state ``done``, which carries the flag approved (spec 000572).

    The booking ``parent`` (300) has the sub-booking ``child`` (100); ``income`` is 75.
    """
    async with maker() as session:
        flow = await seed_agenda_flow(session)
        app = await make_application(session, flow)
        app.amount = Decimal("800.00")
        app.email_confirmed_at = datetime(2026, 10, 1, tzinfo=UTC)
        done = await session.scalar(
            select(State).where(State.flow_version_id == app.flow_version_id, State.key == "done")
        )
        assert done is not None
        done.is_approved = True
        app.current_state_id = done.id
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
        key = f"E{uuid.uuid4().hex[:6]}"
        node = Budget(key=key, path_key=key, name="Kultur")
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


async def test_create_read_change_and_the_rights_of_the_team(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """003022-003026: number, fields, status, version, shop and the team rights."""
    gid, _board = await add_gremium(maker, "Kultur")
    team = await team_of(maker, gid)
    sub = await _sub_team(maker, team)
    person, pid = await add_person(maker, "Ada")
    outsider, _oid = await add_person(maker, "Bo")
    await add_member(maker, gid, pid)
    api.login(person)
    with TestClient(api.app) as client:
        teams = _ok(client.get("/api/events/teams"))
        assert [t["id"] for t in teams] == [str(team)]
        only_title = _event(client, team, "Sommerfest")
        assert only_title["number"].startswith("V-") and len(only_title["number"]) == 10
        assert (only_title["status"], only_title["phase"]) == ("planned", "open")
        assert only_title["teamName"] == "Kultur"
        assert only_title["totals"]["balance"] == "0.00"
        bad_shop = client.post(
            "/api/events",
            json={"teamId": str(team), "title": "X", "shopUrl": "javascript:alert(1)"},
        )
        assert _code(bad_shop, 422) == "event_url_invalid"
        early = client.post(
            "/api/events",
            json={
                "teamId": str(team),
                "title": "X",
                "startsOn": "2026-11-20",
                "endsOn": "2026-11-19",
            },
        )
        assert early.status_code == 422
        assert (
            client.post("/api/events", json={"teamId": str(team), "title": "x" * 301}).status_code
            == 422
        )
        foreign = client.post("/api/events", json={"teamId": str(sub), "title": "X"})
        assert _code(foreign, 403) == "event_team_forbidden"
        full = _event(client, team, "Erstiparty", shopUrl="https://shop.example/x", **EVENT)
        changed = _ok(
            client.patch(
                f"/api/events/{full['id']}",
                json={"version": full["version"], "place": "Aula", "participants": 120},
            )
        )
        assert (changed["place"], changed["participants"], changed["version"]) == ("Aula", 120, 2)
        stale = client.patch(f"/api/events/{full['id']}", json={"version": 1, "place": "X"})
        assert _code(stale, 409) == "event_version_conflict"
        backwards = client.patch(
            f"/api/events/{full['id']}", json={"version": 2, "endsOn": "2026-11-01"}
        )
        assert _code(backwards, 422) == "event_dates_invalid"
        settled = _ok(
            client.post(
                f"/api/events/{full['id']}/status", json={"status": "settled", "version": 2}
            )
        )
        assert (settled["status"], settled["phase"]) == ("settled", "done")
        unknown = client.post(
            f"/api/events/{full['id']}/status", json={"status": "nope", "version": 3}
        )
        assert _code(unknown, 422) == "status_unknown"
        api.login(outsider)
        assert client.get(f"/api/events/{full['id']}").status_code == 404
        assert _ok(client.get("/api/events"))["items"] == []
        api.login(person)
        assert client.delete(f"/api/events/{full['id']}").status_code == 204
        assert client.get(f"/api/events/{full['id']}").status_code == 404
        with_event = client.post(
            "/api/todos/cards",
            json={"boardId": str(_board), "title": "Party", "event": EVENT},
        )
        assert with_event.status_code == 422


async def test_a_member_of_the_parent_team_only_gets_404(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """003026: a member of the parent team does not read the Event of a sub-team."""
    gid, _board = await add_gremium(maker, "Kultur")
    team = await team_of(maker, gid)
    sub = await _sub_team(maker, team)
    member, mid = await add_person(maker, "Ada")
    parent_member, pid = await add_person(maker, "Bo")
    await add_member(maker, gid, pid)
    async with maker() as session:
        await session.execute(
            text("INSERT INTO team_member (team_id, principal_id, role) VALUES (:t, :p, 'member')"),
            {"t": sub, "p": mid},
        )
        await session.commit()
    api.login(member)
    with TestClient(api.app) as client:
        own = _event(client, sub, "Workshop")
        api.login(parent_member)
        assert client.get(f"/api/events/{own['id']}").status_code == 404


async def test_totals_decisions_and_one_event_per_element(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """003029, 003033 and 000479, 000481, 000482."""
    ids = await _money(maker)
    gid, board = await add_gremium(maker, "Kultur")
    team = await team_of(maker, gid)
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid)
    admin = Principal(sub=person.sub, roles=["admin"], permissions=set())
    api.login(admin)
    with TestClient(api.app) as client:
        party = _event(client, team, "Erstiparty", **EVENT)
        for kind, key in (
            ("application", "app"),
            ("agenda_item", "item"),
            ("vote", "vote"),
            ("expense", "parent"),
            ("expense", "child"),
            ("expense", "income"),
        ):
            _ok(
                client.post(
                    "/api/links",
                    json={
                        "a": {"kind": "event", "id": party["id"]},
                        "b": {"kind": kind, "id": str(ids[key])},
                    },
                ),
                201,
            )
        detail = _ok(client.get(f"/api/events/{party['id']}"))
        assert detail["totals"] == {
            "requested": "800.00",
            "approved": "500.00",
            "expenses": "300.00",
            "income": "75.00",
            "balance": "-225.00",
        }
        decisions = detail["decisions"]
        assert [(d["kind"], d["result"]) for d in decisions] == [
            ("vote", "rejected"),
            ("decision", "passed"),
        ]
        assert decisions[1]["amount"] == "500.00"
        other = _event(client, team, "Sommerfest")
        taken = client.post(
            "/api/links",
            json={
                "a": {"kind": "event", "id": other["id"]},
                "b": {"kind": "expense", "id": str(ids["parent"])},
            },
        )
        assert _code(taken, 409) == "event_link_taken"
        rows = _ok(client.get("/api/links", params={"kind": "expense", "id": ids["parent"]}))
        assert [(r["kind"], r["title"]) for r in rows["links"]] == [("event", "Erstiparty")]
        assert rows["links"][0]["url"] == f"/events?id={party['id']}"
        card = _ok(
            client.post("/api/todos/cards", json={"boardId": str(board), "title": "Plakate"}),
            201,
        )
        _ok(
            client.post(
                "/api/links",
                json={
                    "a": {"kind": "todo", "id": card["id"]},
                    "b": {"kind": "event", "id": party["id"]},
                },
            ),
            201,
        )
        refs = _ok(client.get("/api/events/refs", params={"q": "Ersti"}))
        assert [r["title"] for r in refs] == ["Erstiparty"]


async def test_series_editions_and_segments(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """003028, 003029 and 000483: the series, the other editions and the segments."""
    gid, _board = await add_gremium(maker, "Kultur")
    team = await team_of(maker, gid)
    other_gid, _other_board = await add_gremium(maker, "AStA")
    other_team = await team_of(maker, other_gid)
    person, pid = await add_person(maker, "Ada")
    stranger, sid = await add_person(maker, "Bo")
    await add_member(maker, gid, pid)
    await add_member(maker, other_gid, sid)
    api.login(person)
    with TestClient(api.app) as client:
        series = _ok(client.post("/api/events/series", json={"name": "Erstiparty"}), 201)
        assert _code(client.post("/api/events/series", json={"name": "erstiparty"}), 409) == (
            "series_exists"
        )
        listed = _ok(client.get("/api/events/series", params={"q": "ersti"}))
        assert [s["name"] for s in listed] == ["Erstiparty"]
        yesterday = (TODAY - timedelta(days=1)).isoformat()
        tomorrow = (TODAY + timedelta(days=1)).isoformat()
        old = _event(client, team, "Erstiparty SoSe", startsOn=yesterday, seriesId=series["id"])
        new = _event(client, team, "Erstiparty WiSe", startsOn=tomorrow, seriesId=series["id"])
        done = _event(client, team, "Erstiparty 2025", startsOn="2025-10-01")
        _ok(
            client.post(
                f"/api/events/{done['id']}/status", json={"status": "settled", "version": 1}
            )
        )
        api.login(stranger)
        _event(client, other_team, "Erstiparty AStA", seriesId=series["id"])
        api.login(person)
        detail = _ok(client.get(f"/api/events/{new['id']}"))
        assert [e["title"] for e in detail["editions"]] == ["Erstiparty SoSe"]
        assert detail["hiddenEditions"] == 1
        assert detail["seriesName"] == "Erstiparty"

        def titles(**params: Any) -> list[str]:
            return [e["title"] for e in _ok(client.get("/api/events", params=params))["items"]]

        assert titles(segment="upcoming") == ["Erstiparty WiSe"]
        assert titles(segment="past") == ["Erstiparty SoSe"]
        assert titles(segment="done") == ["Erstiparty 2025"]
        assert titles(segment="void") == []
        assert titles(series=series["id"], segment="past") == [old["title"]]
        assert titles(q="WiSe") == ["Erstiparty WiSe"]


async def test_search_calendar_export_and_webhooks(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """003033 and 003034: the search, the calendar entries, the export and the events."""
    gid, _board = await add_gremium(maker, "Kultur")
    team = await team_of(maker, gid)
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid)
    async with maker() as session:
        session.add(
            Webhook(
                name="kultur",
                url="https://hooks.example.org/kultur",
                active=True,
                secret=b"k",
                subscriptions=[
                    {"event": "event.created", "fields": ["number", "title", "teamName"]},
                    {"event": "event.status_changed", "fields": ["status", "fromStatus"]},
                ],
            )
        )
        await session.commit()
    api.login(person)
    with TestClient(api.app) as client:
        party = _event(client, team, "Erstiparty", **EVENT)
        _event(client, team, "Erstiparty ohne Datum")
        _ok(
            client.post(
                f"/api/events/{party['id']}/status",
                json={"status": "settled", "version": party["version"]},
            )
        )
        hits = _ok(client.get("/api/search", params={"q": "Erstiparty"}))["hits"]
        events = [h for h in hits if h["kind"] == "event"]
        assert {h["title"] for h in events} == {"Erstiparty", "Erstiparty ohne Datum"}
        found = next(h for h in events if h["title"] == "Erstiparty")
        assert found["url"] == f"/events?id={party['id']}"
        entries = _ok(
            client.get("/api/calendar/entries", params={"from": "2026-11-01", "to": "2026-11-30"})
        )
        mine = [e for e in entries["items"] if e["kind"] == "event"]
        assert [(e["id"], e["source"]) for e in mine] == [(party["id"], "Kultur")]
        assert client.get("/api/events/export.xlsx").status_code == 403
        api.login(Principal(sub=person.sub, permissions={"finance.export"}))
        export = client.get("/api/events/export.xlsx", params={"q": "Erstiparty"})
        assert export.status_code == 200, export.text
        assert export.content[:2] == b"PK"
    async with maker() as session:
        deliveries = list(
            await session.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at))
        )
    payloads = [(d.event, d.payload) for d in deliveries]
    assert [name for name, _ in payloads] == [
        "event.created",
        "event.created",
        "event.status_changed",
    ]
    created, changed = payloads[0][1], payloads[2][1]
    assert created["data"] == {
        "number": party["number"],
        "title": "Erstiparty",
        "teamName": "Kultur",
    }
    assert created["eventId"] == party["id"]
    assert changed["data"] == {"status": "settled", "fromStatus": "planned"}
