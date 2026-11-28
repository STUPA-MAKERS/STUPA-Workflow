"""The pretix and Mollie integrations on a real Postgres, against a fake pretix and Mollie.

§F/integrations/pretix/003080, mollie/003092 the admin pages save the connection, test it and
need their permission. §NF/security/network/003100, 003101 the allowlist and no read returns
the token. §F/integrations/pretix/003083 the link, its shop and 409 for a second Event.
§003084 the section "Verkauf". §003085 the action "Aktualisieren", once a minute.
§003086 one booking per paid order and per refund, each once, and a failure with its cause.
§003090 the audit entries. §F/integrations/mollie/003094-003097, 003103 the read of the
payments, the fees with one sub-booking per Event, and the money without an Event.
§003104 the action "Daten abrufen" and 409 `sync_running`.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import BudgetExpense
from app.modules.budget.tree_schemas import BudgetNodeCreate, FiscalYearCreate
from app.modules.event_sales.router import get_factories
from app.modules.event_sales.sync import Factories, try_lock
from app.modules.pretix.models import PretixEventLink
from app.modules.todos.models import Link
from app.settings import Settings
from tests._support.guest_apps import build_api, guest_settings
from tests._support.sales_fakes import (
    MOLLIE_TOKEN,
    ORGANIZER,
    PRETIX_HOST,
    PRETIX_TOKEN,
    PRETIX_URL,
    FakeMollie,
    FakePretix,
    money,
)
from tests.integration.conftest import clear_privacy_tables
from tests.integration.modules.todos.conftest import add_gremium, add_member, add_person, team_of

pytestmark = pytest.mark.integration

Maker = async_sessionmaker[AsyncSession]

_ADMIN = Principal(sub="sales-admin", roles=["admin"], email="admin@example.org")
_NOBODY = Principal(sub="sales-nobody", roles=["member"], email="nobody@example.org")

_SALES_TABLES = (
    "pretix_settings, pretix_event_link, pretix_booking, mollie_settings, mollie_payment, "
    "mollie_move, mollie_settlement, mollie_booking"
)


def _clear(eng: Engine) -> None:
    clear_privacy_tables(eng)
    with eng.begin() as conn:
        conn.execute(text(f"TRUNCATE {_SALES_TABLES} RESTART IDENTITY CASCADE"))
        conn.execute(text("DELETE FROM team WHERE gremium_id IS NULL"))
        conn.execute(text("DELETE FROM gremium WHERE slug LIKE 'todo-%'"))


@pytest.fixture
def clean(engine: Engine) -> Iterator[Engine]:
    _clear(engine)
    try:
        yield engine
    finally:
        _clear(engine)


@pytest.fixture
async def maker(migrated: tuple[str, str], clean: Engine) -> AsyncIterator[Maker]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1]).model_copy(update={"pretix_host_allowlist": [PRETIX_HOST]})


def _pretix() -> FakePretix:
    return FakePretix(
        events=[
            {
                "slug": "party",
                "name": {"de": "Semesterparty"},
                "date_from": "2026-12-11T20:00:00Z",
                "public_url": f"{PRETIX_URL}/{ORGANIZER}/party/",
            },
            {"slug": "fahrt", "name": "Erstifahrt", "date_from": "2026-10-01T08:00:00Z"},
        ],
        items={"party": [{"id": 1, "name": "Vorverkauf"}]},
        quotas={"party": [{"name": "Einlass", "available_number": 98}]},
        orders={
            "party": [
                {
                    "code": "AAA11",
                    "status": "p",
                    "total": "10.00",
                    "payment_date": "2026-11-20",
                    "positions": [{"item": 1}],
                    "payments": [{"local_id": 1, "state": "confirmed", "amount": "10.00"}],
                },
                {
                    "code": "CCC33",
                    "status": "c",
                    "total": "10.00",
                    "payment_date": "2026-11-21",
                    "positions": [{"item": 1}],
                    "payments": [{"local_id": 1, "state": "confirmed", "amount": "10.00"}],
                    "refunds": [
                        {
                            "local_id": 1,
                            "state": "done",
                            "amount": "10.00",
                            "execution_date": "2026-11-22",
                        }
                    ],
                },
            ]
        },
    )


def _mollie() -> FakeMollie:
    return FakeMollie(
        payments=[
            {
                "id": "tr_party",
                "amount": money("10.00"),
                "status": "paid",
                "createdAt": "2026-11-20T10:00:00+00:00",
                "paidAt": "2026-11-20T10:01:00+00:00",
                "settlementId": "stl_1",
                "metadata": {"organizer": ORGANIZER, "event": "party"},
            },
            {
                "id": "tr_loose",
                "amount": money("5.00"),
                "status": "paid",
                "createdAt": "2026-11-21T10:00:00+00:00",
                "paidAt": "2026-11-21T10:01:00+00:00",
                "metadata": {"organizer": ORGANIZER, "event": "unbekannt"},
            },
        ],
        refunds=[
            {
                "id": "re_loose",
                "paymentId": "tr_loose",
                "amount": money("1.00"),
                "status": "refunded",
                "createdAt": "2026-11-22T10:00:00+00:00",
            }
        ],
        settlements=[
            {
                "id": "stl_1",
                "reference": "1234.2611.01",
                "status": "paidout",
                "settledAt": "2026-11-26T08:00:00+00:00",
                "amount": money("9.40"),
                "periods": {"2026": {"11": {"costs": [{"amountGross": money("0.60")}]}}},
            }
        ],
        transactions=[
            {"type": "payment", "context": {"paymentId": "tr_party"}, "deductions": money("-0.32")}
        ],
    )


@dataclass
class World:
    app: FastAPI
    pretix: FakePretix
    mollie: FakeMollie

    def login(self, principal: Principal | None) -> None:
        self.app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture
def world(
    migrated: tuple[str, str], settings: Settings, maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> World:
    app = build_api(migrated[1], settings, monkeypatch)
    state = World(app=app, pretix=_pretix(), mollie=_mollie())
    app.dependency_overrides[get_factories] = lambda: Factories(
        pretix=state.pretix.client, mollie=state.mollie.client
    )
    state.login(None)
    return state


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _code(resp: Any, status: int) -> str:
    assert resp.status_code == status, resp.text
    return resp.json()["code"]


async def _cost_centres(maker: Maker) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A Kostenstelle with two leaves and the fiscal year 2026. Return parent and leaves."""
    async with maker() as session:
        svc = BudgetTreeService(session, actor="tester")
        top = await svc.create_node(
            BudgetNodeCreate(key=f"S{uuid.uuid4().hex[:6]}", name="Veranstaltungen")
        )
        income = await svc.create_node(BudgetNodeCreate(key="1", name="Einnahmen", parentId=top.id))
        fees = await svc.create_node(BudgetNodeCreate(key="2", name="Gebühren", parentId=top.id))
        await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
        await session.commit()
        return top.id, income.id, fees.id


async def _person(maker: Maker, *permissions: str) -> tuple[Principal, uuid.UUID]:
    """A member of a Gremium whose team holds the Events, with global permissions."""
    gid, _board = await add_gremium(maker, "Kultur")
    person, pid = await add_person(maker, "Ada")
    await add_member(maker, gid, pid)
    principal = Principal(
        sub=person.sub, email=person.email, display_name="Ada", permissions=set(permissions)
    )
    return principal, await team_of(maker, gid)


def _connect_pretix(client: TestClient, **switches: bool) -> None:
    _ok(
        client.put(
            "/api/admin/pretix",
            json={
                "baseUrl": f"{PRETIX_URL}/",
                "organizer": ORGANIZER,
                "token": PRETIX_TOKEN,
                "showSales": switches.get("show", True),
                "bookIncome": switches.get("book", True),
            },
        )
    )


async def _expenses(maker: Maker) -> list[BudgetExpense]:
    async with maker() as session:
        return list(
            (await session.scalars(select(BudgetExpense).order_by(BudgetExpense.description))).all()
        )


async def _event_links(maker: Maker, event_id: str) -> set[uuid.UUID]:
    async with maker() as session:
        rows = (
            await session.scalars(
                select(Link).where(Link.a_kind == "event", Link.a_id == uuid.UUID(event_id))
            )
        ).all()
        rows_b = (
            await session.scalars(
                select(Link).where(Link.b_kind == "event", Link.b_id == uuid.UUID(event_id))
            )
        ).all()
        return {r.b_id for r in rows} | {r.a_id for r in rows_b}


def test_the_admin_routes_need_their_permission(world: World) -> None:
    world.login(_NOBODY)
    with TestClient(world.app) as client:
        assert client.get("/api/admin/pretix").status_code == 403
        assert client.put("/api/admin/pretix", json={}).status_code in (403, 422)
        assert client.post("/api/admin/pretix/test").status_code == 403
        assert client.get("/api/admin/pretix/failed-bookings").status_code == 403
        assert client.get("/api/admin/mollie").status_code == 403
        assert client.post("/api/admin/mollie/test").status_code == 403
        assert client.get("/api/admin/mollie/failed-bookings").status_code == 403
        assert client.get("/api/pretix/events").status_code == 403
        assert (
            _code(client.post("/api/sales-sync", params={"page": "bookings"}), 403)
            == "sync_forbidden"
        )


async def test_the_connections_save_test_and_never_return_the_token(
    world: World, maker: Maker
) -> None:
    world.login(_ADMIN)
    with TestClient(world.app) as client:
        empty = _ok(client.get("/api/admin/pretix"))
        assert empty["tokenSet"] is False
        assert empty["allowedHosts"] == [PRETIX_HOST]
        assert _ok(client.post("/api/admin/pretix/test")) == {
            "ok": False,
            "error": "not_configured",
            "name": None,
        }
        refused = client.put(
            "/api/admin/pretix",
            json={
                "baseUrl": "https://evil.test",
                "organizer": ORGANIZER,
                "token": "x" * 10,
                "showSales": True,
                "bookIncome": False,
            },
        )
        assert _code(refused, 422) == "pretix_host_not_allowed"
        _connect_pretix(client)
        saved = _ok(client.get("/api/admin/pretix"))
        assert saved["baseUrl"] == PRETIX_URL
        assert saved["tokenSet"] is True
        assert PRETIX_TOKEN not in str(saved)
        assert _ok(client.post("/api/admin/pretix/test"))["ok"] is True
        moved = client.put(
            "/api/admin/pretix",
            json={
                "baseUrl": f"{PRETIX_URL}/other",
                "organizer": ORGANIZER,
                "showSales": True,
                "bookIncome": True,
            },
        )
        assert _code(moved, 422) == "token_required"
        world.pretix.status = 401
        assert _ok(client.post("/api/admin/pretix/test"))["error"] == "unauthorized"

        assert _ok(client.get("/api/admin/mollie"))["tokenSet"] is False
        mollie = _ok(client.put("/api/admin/mollie", json={"token": MOLLIE_TOKEN}))
        assert mollie["tokenSet"] is True
        assert MOLLIE_TOKEN not in str(mollie)
        assert _ok(client.post("/api/admin/mollie/test")) == {
            "ok": True,
            "error": None,
            "name": "Studierendenschaft",
        }
        assert _ok(client.get("/api/admin/mollie"))["organization"] == "Studierendenschaft"
        assert _ok(client.get("/api/sales-sync")) == {"pretix": True, "mollie": True}
        _ok(client.put("/api/admin/mollie", json={"clearToken": True}))
        assert _ok(client.get("/api/sales-sync")) == {"pretix": True, "mollie": False}
    async with maker() as session:
        actions = (await session.scalars(select(AuditEntry.action))).all()
    assert "pretix_connection" in actions
    assert "mollie_connection" in actions


async def test_link_sales_refresh_and_one_booking_per_order(world: World, maker: Maker) -> None:
    parent, income, fees = await _cost_centres(maker)
    person, team = await _person(maker, "pretix.use", "budget.book")
    world.login(_ADMIN)
    with TestClient(world.app) as client:
        _connect_pretix(client)
        world.login(person)
        first = _ok(client.post("/api/events", json={"teamId": str(team), "title": "Party"}), 201)
        second = _ok(
            client.post("/api/events", json={"teamId": str(team), "title": "Party 2"}), 201
        )
        assert [e["taken"] for e in _ok(client.get("/api/pretix/events"))] == [False, False]

        link = _ok(client.put(f"/api/pretix/links/{first['id']}", json={"slug": "party"}))
        assert link["name"] == "Semesterparty"
        assert (
            _ok(client.get(f"/api/events/{first['id']}"))["shopUrl"]
            == f"{PRETIX_URL}/{ORGANIZER}/party/"
        )
        taken = client.put(f"/api/pretix/links/{second['id']}", json={"slug": "party"})
        assert _code(taken, 409) == "pretix_event_taken"
        unknown = client.put(f"/api/pretix/links/{second['id']}", json={"slug": "nope"})
        assert _code(unknown, 404) == "pretix_event_unknown"
        assert [e["taken"] for e in _ok(client.get("/api/pretix/events"))] == [True, False]

        before = _ok(client.get(f"/api/events/{first['id']}/sales"))
        assert before["link"]["slug"] == "party"
        assert before["pretix"] is None
        assert before["refreshable"] is True

        _ok(
            client.put(
                f"/api/pretix/links/{first['id']}/income-budget", json={"budgetId": str(parent)}
            )
        )
        failed = _ok(client.post(f"/api/events/{first['id']}/sales/refresh"))
        assert failed["booked"] == 0
        assert {f["cause"] for f in failed["failures"]} == {"cost_centre_not_leaf"}
        assert (
            _code(client.post(f"/api/events/{first['id']}/sales/refresh"), 429)
            == "refresh_too_soon"
        )

        world.login(_ADMIN)
        listed = _ok(client.get("/api/admin/pretix/failed-bookings"))["items"]
        assert {item["key"] for item in listed} == {"AAA11", "CCC33", "CCC33-1"}
        world.login(person)

        _ok(
            client.put(
                f"/api/pretix/links/{first['id']}/income-budget", json={"budgetId": str(income)}
            )
        )
        booked = _ok(client.post("/api/sales-sync", params={"page": "events"}))
        assert booked == {"booked": 3, "failures": []}
        again = _ok(client.post("/api/sales-sync", params={"page": "bookings"}))
        assert again == {"booked": 0, "failures": []}

        sales = _ok(client.get(f"/api/events/{first['id']}/sales"))
        assert sales["pretix"]["paidSum"] == "10.00"
        assert sales["pretix"]["refundSum"] == "10.00"
        assert sales["pretix"]["products"] == [
            {"name": "Vorverkauf", "paid": 1, "pending": 0, "cancelled": 1}
        ]
        assert sales["pretix"]["quotas"] == [{"name": "Einlass", "available": 98}]
        assert sales["link"]["incomeBudgetName"]

        world.login(_ADMIN)
        assert _ok(client.get("/api/admin/pretix/failed-bookings"))["items"] == []
        world.login(person)
        _ok(client.delete(f"/api/pretix/links/{first['id']}"), 204)
        assert _ok(client.get(f"/api/events/{first['id']}/sales"))["link"] is None

    expenses = await _expenses(maker)
    assert sorted((e.kind, e.amount) for e in expenses) == [
        ("expense", Decimal("10.00")),
        ("income", Decimal("10.00")),
        ("income", Decimal("10.00")),
    ]
    assert {e.budget_id for e in expenses} == {income}
    assert await _event_links(maker, first["id"]) == {e.id for e in expenses}
    assert fees
    assert {r.method for r in world.pretix.requests} == {"GET"}
    async with maker() as session:
        actions = (await session.scalars(select(AuditEntry.action))).all()
    assert {"pretix_link", "pretix_unlink"} <= set(actions)


async def test_mollie_books_fees_per_event_and_money_without_an_event(
    world: World, maker: Maker
) -> None:
    _parent, income, fees = await _cost_centres(maker)
    person, team = await _person(maker, "pretix.use", "budget.book")
    world.login(_ADMIN)
    with TestClient(world.app) as client:
        _connect_pretix(client)
        world.login(person)
        event = _ok(client.post("/api/events", json={"teamId": str(team), "title": "Party"}), 201)
        _ok(client.put(f"/api/pretix/links/{event['id']}", json={"slug": "party"}))
        world.login(_ADMIN)
        _ok(
            client.put(
                "/api/admin/mollie",
                json={
                    "token": MOLLIE_TOKEN,
                    "feeBudgetId": str(fees),
                    "unassignedBudgetId": str(income),
                },
            )
        )
        world.login(person)
        result = _ok(client.post("/api/sales-sync", params={"page": "bookings"}))
        assert result == {"booked": 3, "failures": []}
        assert _ok(client.post("/api/sales-sync", params={"page": "bookings"}))["booked"] == 0

        money_out = _ok(client.get(f"/api/events/{event['id']}/sales"))["mollie"]
        assert money_out["paid"] == "10.00"
        assert money_out["fees"] == "0.32"
        assert [s["reference"] for s in money_out["settlements"]] == ["1234.2611.01"]

        world.pretix.status = 500
        world.mollie.status = 503
        broken = _ok(client.post("/api/sales-sync", params={"page": "events"}))
        assert {(f["integration"], f["cause"]) for f in broken["failures"]} >= {
            ("mollie", "status")
        }
        world.login(_ADMIN)
        state = _ok(client.get("/api/admin/mollie"))
        assert state["readError"] == "status"
        assert state["readOkAt"] is not None
        assert _ok(client.get("/api/admin/mollie/failed-bookings"))["items"] == []

    expenses = await _expenses(maker)
    fee = next(e for e in expenses if e.budget_id == fees and e.parent_expense_id is None)
    parts = sorted(e.amount for e in expenses if e.parent_expense_id == fee.id)
    assert fee.amount == Decimal("0.60")
    assert parts == [Decimal("0.28"), Decimal("0.32")]
    loose = sorted((e.kind, e.amount) for e in expenses if e.budget_id == income)
    assert loose == [("expense", Decimal("1.00")), ("income", Decimal("5.00"))]
    event_part = next(
        e for e in expenses if e.parent_expense_id == fee.id and e.amount == Decimal("0.32")
    )
    assert await _event_links(maker, event["id"]) == {event_part.id}
    assert {r.method for r in world.mollie.requests} == {"GET"}


async def test_a_second_run_during_a_run_gets_409(world: World, maker: Maker) -> None:
    person, _team = await _person(maker, "budget.book")
    world.login(_ADMIN)
    with TestClient(world.app) as client:
        _connect_pretix(client)
        world.login(person)
        async with maker() as holder:
            assert await try_lock(holder)
            busy = client.post("/api/sales-sync", params={"page": "bookings"})
            await holder.rollback()
        assert _code(busy, 409) == "sync_running"
        assert _ok(client.post("/api/sales-sync", params={"page": "bookings"}))["booked"] == 0


async def test_without_a_connection_the_sync_and_the_picker_are_off(
    world: World, maker: Maker
) -> None:
    person, team = await _person(maker, "pretix.use", "budget.book")
    world.login(person)
    with TestClient(world.app) as client:
        assert _ok(client.get("/api/sales-sync")) == {"pretix": False, "mollie": False}
        assert (
            _code(client.post("/api/sales-sync", params={"page": "bookings"}), 404)
            == "feature_disabled"
        )
        assert _code(client.get("/api/pretix/events"), 404) == "pretix_off"
        event = _ok(client.post("/api/events", json={"teamId": str(team), "title": "X"}), 201)
        assert (
            _code(client.put(f"/api/pretix/links/{event['id']}", json={"slug": "party"}), 404)
            == "pretix_off"
        )
        sales = _ok(client.get(f"/api/events/{event['id']}/sales"))
        assert sales["connected"] is False
        assert sales["linkable"] is False
        assert _ok(client.post(f"/api/events/{event['id']}/sales/refresh")) == {
            "booked": 0,
            "failures": [],
        }
        world.login(_ADMIN)
        _connect_pretix(client)
        world.pretix.down = True
        world.login(person)
        assert _code(client.get("/api/pretix/events"), 503) == "pretix_unavailable"
        assert (
            _code(client.put(f"/api/pretix/links/{event['id']}", json={"slug": "party"}), 503)
            == "pretix_unavailable"
        )


async def test_the_worker_reads_the_active_links(
    world: World, maker: Maker, settings: Settings
) -> None:
    from worker.event_sales import read_mollie_money, read_pretix_sales

    _parent, income, _fees = await _cost_centres(maker)
    person, team = await _person(maker, "pretix.use", "budget.book")
    world.login(_ADMIN)
    with TestClient(world.app) as client:
        _connect_pretix(client)
        world.login(person)
        event = _ok(client.post("/api/events", json={"teamId": str(team), "title": "Party"}), 201)
        _ok(client.put(f"/api/pretix/links/{event['id']}", json={"slug": "party"}))
        _ok(
            client.put(
                f"/api/pretix/links/{event['id']}/income-budget", json={"budgetId": str(income)}
            )
        )
    ctx: dict[str, Any] = {
        "settings": settings,
        "sales_sessionmaker": maker,
        "sales_factories": Factories(pretix=world.pretix.client, mollie=world.mollie.client),
    }
    await read_pretix_sales(ctx)
    await read_mollie_money(ctx)
    await read_pretix_sales(ctx)
    async with maker() as session:
        row = await session.scalar(select(PretixEventLink))
        assert row is not None
        assert row.sales_ok_at is not None
        await session.execute(
            update(PretixEventLink).values(sales_ok_at=datetime.now(UTC) - timedelta(days=1))
        )
        await session.commit()
    assert len(await _expenses(maker)) == 3


async def test_a_token_reads_the_sums_and_never_calls_pretix_or_mollie(
    world: World, maker: Maker
) -> None:
    person, team = await _person(maker, "pretix.use", "budget.book")
    world.login(_ADMIN)
    with TestClient(world.app) as client:
        _connect_pretix(client)
        world.login(person)
        event = _ok(client.post("/api/events", json={"teamId": str(team), "title": "Party"}), 201)
        token = Principal(
            sub=person.sub,
            email=person.email,
            permissions={"pretix.use", "budget.book"},
            scope_permissions=frozenset({"pretix.use", "budget.book", "todo.write"}),
        )
        world.login(token)
        assert _ok(client.get(f"/api/events/{event['id']}/sales"))["connected"] is True
        refused = [
            client.get("/api/pretix/events"),
            client.put(f"/api/pretix/links/{event['id']}", json={"slug": "party"}),
            client.delete(f"/api/pretix/links/{event['id']}"),
            client.put(f"/api/pretix/links/{event['id']}/income-budget", json={"budgetId": None}),
            client.post(f"/api/events/{event['id']}/sales/refresh"),
            client.post("/api/sales-sync", params={"page": "bookings"}),
        ]
        assert [_code(r, 403) for r in refused] == ["cookie_session_required"] * len(refused)
        admin_token = Principal(
            sub="sales-admin",
            roles=["admin"],
            scope_permissions=frozenset({"admin.pretix", "admin.mollie"}),
        )
        world.login(admin_token)
        assert _code(client.post("/api/admin/pretix/test"), 403) == "cookie_session_required"
        assert _code(client.post("/api/admin/mollie/test"), 403) == "cookie_session_required"
    assert world.pretix.requests == []
