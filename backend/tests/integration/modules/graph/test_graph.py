"""Integration: the graph page (specs 001420-001432) on a real Postgres.

The world of each test is the one of ``_money``: an Antrag with a vote, a meeting of a
Gremium with a TOP and its vote, and three Buchungen on one cost centre. The read rules
are the real ones of the modules.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import BudgetExpense, Invoice
from app.modules.calendar.models import Appointment, Invitation
from app.modules.graph.build import Filters
from app.modules.graph.schemas import GraphPage
from app.modules.graph.service import GraphService
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.site_config.features import Feature
from app.modules.tickets.models import Ticket
from app.modules.todos.models import Link, TodoCard, TodoColumn
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person
from tests.integration.modules.todos.test_todos_events import _money

pytestmark = pytest.mark.integration

Ref = tuple[str, uuid.UUID]


async def _admin(maker: async_sessionmaker[AsyncSession]) -> tuple[Principal, uuid.UUID]:
    person, person_id = await add_person(maker, "Admin")
    return Principal(sub=person.sub, roles=["admin"], permissions=set()), person_id


async def _world(maker: async_sessionmaker[AsyncSession]) -> dict[str, uuid.UUID]:
    """The ids of ``_money`` with the meeting, its Gremium and the cost centre."""
    ids = await _money(maker)
    async with maker() as session:
        item = await session.get(MeetingAgendaItem, ids["item"])
        assert item is not None
        meeting = await session.get(Meeting, item.meeting_id)
        assert meeting is not None
        income = await session.get(BudgetExpense, ids["income"])
        assert income is not None
        return {
            **ids,
            "meeting": meeting.id,
            "gremium": meeting.gremium_id,
            "budget": income.budget_id,
        }


async def _invoice(maker: async_sessionmaker[AsyncSession], day: date) -> uuid.UUID:
    async with maker() as session:
        row = Invoice(number="R-1", issue_date=day, gross_amount=Decimal("10.00"))
        session.add(row)
        await session.commit()
        return row.id


async def _card(
    maker: async_sessionmaker[AsyncSession], board_id: uuid.UUID, creator: uuid.UUID, title: str
) -> uuid.UUID:
    async with maker() as session:
        column = await session.scalar(
            select(TodoColumn).where(TodoColumn.board_id == board_id).limit(1)
        )
        assert column is not None
        card = TodoCard(
            board_id=board_id,
            column_id=column.id,
            rank=uuid.uuid4().hex,
            title=title,
            created_by=creator,
        )
        session.add(card)
        await session.commit()
        return card.id


async def _link(
    maker: async_sessionmaker[AsyncSession], one: Ref, other: Ref, actor: uuid.UUID
) -> None:
    async with maker() as session:
        session.add(Link.between(one, other, actor))
        await session.commit()


def _refs(page: GraphPage) -> set[Ref]:
    return {(n.kind, n.id) for n in page.nodes}


def _lines(page: GraphPage) -> set[tuple[frozenset[Ref], str]]:
    return {(frozenset(((e.a.kind, e.a.id), (e.b.kind, e.b.id))), e.source) for e in page.edges}


async def _page(
    maker: async_sessionmaker[AsyncSession],
    principal: Principal,
    filters: Filters | None = None,
    cursor: str | None = None,
) -> GraphPage:
    async with maker() as session:
        return await GraphService(session).page(principal, filters or Filters(), cursor)


async def test_the_graph_shows_links_and_builtin_relations(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Specs 001420, 001423, 001424: the nodes with a relation and both sorts of lines."""
    ids = await _world(maker)
    admin, admin_id = await _admin(maker)
    invoice = await _invoice(maker, date(2020, 3, 1))
    await _invoice(maker, date(2020, 3, 2))
    app: Ref = ("application", ids["app"])
    await _link(maker, app, ("invoice", invoice), admin_id)
    await _link(maker, ("vote", ids["vote"]), app, admin_id)

    page = await _page(maker, admin)

    assert _refs(page) == {
        app,
        ("invoice", invoice),
        ("vote", ids["vote"]),
        ("vote", ids["top_vote"]),
        ("meeting", ids["meeting"]),
        ("agenda_item", ids["item"]),
        ("gremium", ids["gremium"]),
        ("expense", ids["parent"]),
        ("expense", ids["child"]),
        ("expense", ids["income"]),
        ("budget", ids["budget"]),
    }
    budget: Ref = ("budget", ids["budget"])
    meeting: Ref = ("meeting", ids["meeting"])
    item: Ref = ("agenda_item", ids["item"])
    assert _lines(page) == {
        (frozenset((app, ("invoice", invoice))), "link"),
        (frozenset((app, ("vote", ids["vote"]))), "link"),
        (frozenset((meeting, ("vote", ids["vote"]))), "builtin"),
        (frozenset((meeting, item)), "builtin"),
        (frozenset((meeting, ("gremium", ids["gremium"]))), "builtin"),
        (frozenset((item, ("vote", ids["top_vote"]))), "builtin"),
        (frozenset((budget, ("expense", ids["parent"]))), "builtin"),
        (frozenset((budget, ("expense", ids["child"]))), "builtin"),
        (frozenset((budget, ("expense", ids["income"]))), "builtin"),
    }
    assert page.next_cursor is None
    by_ref = {(n.kind, n.id): n for n in page.nodes}
    assert by_ref[("invoice", invoice)].date == date(2020, 3, 1)
    assert by_ref[meeting].date == date(2026, 11, 1)
    assert by_ref[item].date == date(2026, 11, 1)
    assert by_ref[budget].date is None
    assert by_ref[meeting].url == f"/meetings/{ids['meeting']}"
    assert all(n.accessible and not n.granted for n in page.nodes)

    with_single = await _page(maker, admin, Filters(single=True))
    assert len(_refs(with_single) - _refs(page)) >= 1
    assert {n.kind for n in with_single.nodes if (n.kind, n.id) not in _refs(page)} >= {"invoice"}

    links_only = await _page(maker, admin, Filters(relations="links"))
    assert _refs(links_only) == {app, ("invoice", invoice), ("vote", ids["vote"])}

    spring = await _page(
        maker, admin, Filters(start=date(2020, 2, 1), end=date(2020, 3, 31), single=True)
    )
    assert {n.kind for n in spring.nodes} <= {"invoice", "gremium", "budget"}
    assert ("invoice", invoice) in _refs(spring)

    assert (await _page(maker, admin, cursor="60")).nodes == ()


async def test_a_reader_sees_only_what_the_kind_or_a_card_opens(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec 001422: the read rule of each kind, the card grant and the grey nodes."""
    ids = await _world(maker)
    _admin_principal, admin_id = await _admin(maker)
    gremium_id, board_id = await add_gremium(maker, "Kultur")
    person, person_id = await add_person(maker, "Ada")
    await add_member(maker, gremium_id, person_id, "todo.write")
    ada = Principal(sub=person.sub, permissions={"graph.view"})
    card: Ref = ("todo", await _card(maker, board_id, admin_id, "Abrechnung"))
    income: Ref = ("expense", ids["income"])
    budget: Ref = ("budget", ids["budget"])
    await _link(maker, card, income, admin_id)
    await _link(maker, card, budget, admin_id)

    page = await _page(maker, ada)

    assert _refs(page) == {card, income, budget}
    assert _lines(page) == {
        (frozenset((card, income)), "link"),
        (frozenset((card, budget)), "link"),
        (frozenset((income, budget)), "builtin"),
    }
    by_ref = {(n.kind, n.id): n for n in page.nodes}
    assert by_ref[card].granted is False
    assert by_ref[income].granted is True
    assert by_ref[income].url is None
    assert by_ref[budget].granted is True
    assert by_ref[budget].url is None

    grey = await _page(maker, ada, Filters(no_access=True))
    hidden = [n for n in grey.nodes if not n.accessible]
    assert {(n.kind, n.id) for n in hidden} == {
        ("expense", ids["parent"]),
        ("expense", ids["child"]),
    }
    assert all(n.title is None and n.url is None and n.date is None for n in hidden)
    assert ("application", ids["app"]) not in _refs(grey)

    stranger_row, _stranger_id = await add_person(maker, "Bo")
    stranger = Principal(sub=stranger_row.sub, permissions={"graph.view"})
    assert (await _page(maker, stranger)).nodes == ()
    assert (await _page(maker, stranger, Filters(no_access=True, single=True))).nodes == ()


async def test_a_termin_a_ticket_and_a_card_take_their_dates(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec 001425: the start of a Termin, the due date of a card, the creation of a ticket."""
    admin, admin_id = await _admin(maker)
    gremium_id, board_id = await add_gremium(maker, "Kultur")
    other_id, _other_board = await add_gremium(maker, "Sport")
    card: Ref = ("todo", await _card(maker, board_id, admin_id, "Raum buchen"))
    async with maker() as session:
        termin = Appointment(
            title="Sommerfest",
            starts_on=date(2020, 7, 1),
            ends_on=date(2020, 7, 1),
            creator_id=admin_id,
        )
        ticket = Ticket(kind="bug", title="Fehler", body="x", reporter_principal_id=admin_id)
        session.add_all([termin, ticket])
        await session.flush()
        session.add_all(
            [
                Invitation(appointment_id=termin.id, gremium_id=gremium_id),
                Invitation(appointment_id=termin.id, gremium_id=other_id),
                Invitation(appointment_id=termin.id, principal_id=admin_id),
            ]
        )
        stored = await session.get(TodoCard, card[1])
        assert stored is not None
        stored.due_date = date(2020, 7, 3)
        await session.commit()
        termin_ref: Ref = ("appointment", termin.id)
        ticket_ref: Ref = ("ticket", ticket.id)
    await _link(maker, card, termin_ref, admin_id)
    await _link(maker, card, ticket_ref, admin_id)

    page = await _page(maker, admin)

    by_ref = {(n.kind, n.id): n for n in page.nodes}
    assert set(by_ref) == {
        card,
        termin_ref,
        ticket_ref,
        ("gremium", gremium_id),
        ("gremium", other_id),
    }
    assert by_ref[termin_ref].date == date(2020, 7, 1)
    assert by_ref[card].date == date(2020, 7, 3)
    assert by_ref[ticket_ref].date is not None
    assert (frozenset((termin_ref, ("gremium", other_id))), "builtin") in _lines(page)

    july = await _page(maker, admin, Filters(start=date(2020, 7, 2), end=date(2020, 7, 31)))
    assert _refs(july) == set()

    found = await _page(maker, admin, Filters(q="sommer", depth=1))
    assert _refs(found) == {termin_ref, card, ("gremium", gremium_id), ("gremium", other_id)}

    # Spec 001434: a neighbour shows also when it does not pass the filters.
    assert _refs(await _page(maker, admin, Filters(q="sommer"))) == set()
    two = await _page(maker, admin, Filters(q="sommer", depth=2))
    assert _refs(two) == _refs(found) | {ticket_ref}
    by_kind = await _page(maker, admin, Filters(kinds=frozenset({"ticket"}), depth=1))
    assert _refs(by_kind) == {ticket_ref, card}


async def test_a_kind_of_a_feature_that_is_off_is_no_node(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 001432: with Rechnungen off the graph has no invoice."""
    ids = await _world(maker)
    admin, admin_id = await _admin(maker)
    invoice = await _invoice(maker, date(2020, 3, 1))
    await _link(maker, ("application", ids["app"]), ("invoice", invoice), admin_id)
    assert ("invoice", invoice) in _refs(await _page(maker, admin))

    async def _without_invoices(_session: AsyncSession) -> frozenset[Feature]:
        return frozenset(Feature) - {Feature.INVOICES}

    monkeypatch.setattr("app.modules.todos.links.active_features", _without_invoices)

    page = await _page(maker, admin, Filters(single=True))
    assert "invoice" not in {n.kind for n in page.nodes}
    assert all("invoice" not in (e.a.kind, e.b.kind) for e in page.edges)


async def test_the_route_reads_the_graph_of_the_caller(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Specs 001421, 001431: the route, its permission and the answer."""
    ids = await _world(maker)
    admin, _admin_id = await _admin(maker)
    person, _person_id = await add_person(maker, "Ada")

    api.login(Principal(sub=person.sub, permissions={"application.read_all"}))
    with TestClient(api.app) as client:
        assert client.get("/api/graph").status_code == 403

    api.login(admin)
    with TestClient(api.app) as client:
        resp = client.get("/api/graph", params={"kinds": ["meeting", "agenda_item"], "depth": 0})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {n["kind"] for n in body["nodes"]} == {"meeting", "agenda_item"}
        # Spec 001434: without ``depth`` the neighbours of the hits show, two steps away.
        near = client.get("/api/graph", params={"kinds": ["meeting", "agenda_item"]})
        assert {n["kind"] for n in near.json()["nodes"]} > {"meeting", "agenda_item"}
        assert body["edges"] == [
            {
                "a": {"kind": "meeting", "id": str(ids["meeting"])},
                "b": {"kind": "agenda_item", "id": str(ids["item"])},
                "source": "builtin",
            }
        ]
        assert body["nextCursor"] is None
        bad = client.get("/api/graph", params={"cursor": "x"})
        assert bad.status_code == 422
        assert bad.json()["code"] == "graph_cursor_invalid"
