"""Bestellungen without an Antrag on a real Postgres.

§ F/finance/orders/003014 a Bestellung can have no Antrag: no positions, no sum and no
timeline entry. § 002863 the persons with ``order.manage`` or ``budget.view`` read it.
§ 002885 the filters read the Kostenstelle and the Haushaltsjahr of its bookings.
§ 002878 a booking gets and loses its Bestellung at the create and at the change.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.applications.models import ApplicationOrderEvent
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Applicant, Principal
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import Budget, FiscalYear
from app.modules.budget.tree_schemas import ExpenseUpdate
from app.modules.config_revision.revert import RevertService
from app.modules.files.models import Attachment
from app.settings import Settings
from app.shared.errors import NotFoundError, ValidationProblem
from tests._support.guest_apps import GuestSeed
from tests._support.memory_storage import MemoryStorage
from tests.integration.modules.orders.test_orders import (
    _FINANCE,
    _LEDGER,
    _PDF,
    _READER,
    _antrag,
    _audit,
    _client,
    _invoice,
    maker,  # noqa: F401
    seed,  # noqa: F401
    settings,  # noqa: F401
)

pytestmark = pytest.mark.integration

_OWNER = Principal(
    sub="free-orders-sub", roles=["member"], permissions={"application.read", "order.manage"}
)
_BOOK_ONLY = Principal(sub="book-sub", roles=["member"], permissions={"budget.book"})


async def _centre(maker: async_sessionmaker[AsyncSession]) -> tuple[uuid.UUID, uuid.UUID]:  # noqa: F811
    """Create a Kostenstelle with an open Haushaltsjahr; return both ids."""
    key = f"KS{uuid.uuid4().hex[:8]}"
    async with maker() as session:
        budget = Budget(key=key, path_key=key, name="Altbestand")
        session.add(budget)
        await session.flush()
        year = FiscalYear(
            budget_id=budget.id,
            year=2026,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        session.add(year)
        await session.commit()
        return budget.id, year.id


async def test_a_bestellung_without_an_antrag(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 003014 + § 002863: the create, the read rule, the changes, the files, the delete."""
    storage = MemoryStorage()
    api = _client(migrated, settings, monkeypatch, _OWNER, storage=storage)
    app_id = await _antrag(maker, seed)
    refused = api.post("/api/orders", json={"title": "Stuhl", "positionIds": ["p1"]})
    assert (refused.status_code, refused.json()["code"]) == (422, "positions_need_application")
    made = api.post("/api/orders", json={"title": "Stuhl", "plannedAmount": "80.00"})
    assert made.status_code == 201, made.text
    order = made.json()
    assert (order["applicationId"], order["applicationTitle"], order["positionIds"]) == (
        None,
        None,
        [],
    )
    url = f"/api/orders/{order['id']}"

    ledger = _client(migrated, settings, monkeypatch, _LEDGER, storage=storage)
    reader = _client(migrated, settings, monkeypatch, _READER, storage=storage)
    guest = _client(migrated, settings, monkeypatch, None, Applicant(application_id=str(app_id)))
    assert ledger.get(url).json()["title"] == "Stuhl"
    assert ledger.post("/api/orders", json={"title": "x"}).status_code == 403
    assert reader.get(url).status_code == 404
    assert guest.get(url).status_code == 404

    changed = api.patch(url, json={"version": 1, "supplier": "Möbelhaus"}).json()
    assert changed["supplier"] == "Möbelhaus"
    late = api.patch(url, json={"version": 2, "positionIds": ["p1"]})
    assert (late.status_code, late.json()["code"]) == (422, "positions_need_application")
    done = api.post(f"{url}/status", json={"status": "cancelled", "version": 2}).json()
    assert done["status"] == "cancelled"
    async with maker() as session:
        events = await session.scalar(select(func.count()).select_from(ApplicationOrderEvent))
        assert events == 0
    assert (await _audit(maker, "order_create"))[-1].data["applicationId"] is None

    files = f"{url}/attachments"
    up = api.post(files, files={"file": ("Beleg.pdf", _PDF, "application/pdf")}).json()
    async with maker() as session:
        await session.execute(update(Attachment).values(scanned=True, scan_result="clean"))
        await session.commit()
    assert len(ledger.get(files).json()) == 1
    assert ledger.get(f"/api/attachments/{up['id']}/download").content == _PDF
    assert reader.get(files).status_code == 404
    assert reader.get(f"/api/attachments/{up['id']}/download").status_code == 404

    async with maker() as session:
        session.add(PrincipalRow(sub=_OWNER.sub, display_name="Ole", email="ole@example.org"))
        await session.commit()
    ends = {
        "a": {"kind": "order", "id": order["id"]},
        "b": {"kind": "application", "id": str(app_id)},
    }
    assert api.post("/api/links", json=ends).status_code == 201
    params = {"kind": "application", "id": str(app_id)}
    assert [row["title"] for row in api.get("/api/links", params=params).json()["links"]] == [
        "Stuhl"
    ]
    hidden = reader.get("/api/links", params=params).json()["links"]
    assert [row.get("title") for row in hidden] != ["Stuhl"]

    assert api.delete(url).status_code == 204
    assert storage.blobs == {}


async def test_the_page_finds_it_by_its_bookings(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 002885 + § 002878: the filters over the bookings, the Bestellung of a booking."""
    api = _client(migrated, settings, monkeypatch, _FINANCE)
    app_id = await _antrag(maker, seed)
    budget_id, year_id = await _centre(maker)
    other_budget, other_year = await _centre(maker)
    of_antrag = api.post(f"/api/applications/{app_id}/orders", json={"title": "Regal"}).json()
    free = api.post("/api/orders", json={"title": "Altkauf", "actualAmount": "30.00"}).json()
    invoice_id = str(await _invoice(maker, "30.00"))
    api.put(f"/api/orders/{free['id']}/invoice", json={"invoiceId": invoice_id, "version": 1})

    def titles(client: object = api, **params: str) -> list[str]:
        answer = client.get("/api/orders", params=params)  # type: ignore[attr-defined]
        return sorted(item["title"] for item in answer.json()["items"])

    assert titles() == ["Altkauf", "Regal"]
    assert titles(withoutApplication="true") == ["Altkauf"]
    assert titles(_client(migrated, settings, monkeypatch, _LEDGER)) == ["Altkauf"]
    assert _client(migrated, settings, monkeypatch, _READER).get("/api/orders").status_code == 403
    assert titles(gremium=str(uuid.uuid4())) == []
    assert titles(fiscalYear=str(year_id)) == []
    assert titles(budget=str(budget_id)) == []

    old = api.post(
        "/api/expenses",
        json={"amount": "30.00", "description": "Altkauf", "budgetId": str(budget_id)},
    )
    assert (old.status_code, old.json()["orderId"]) == (201, None)
    booking = f"/api/budget-expenses/{old.json()['id']}"
    wrong = api.patch(booking, json={"orderId": of_antrag["id"]})
    assert (wrong.status_code, wrong.json()["code"]) == (422, "order_application_mismatch")
    assert api.patch(booking, json={"orderId": str(uuid.uuid4())}).status_code == 404
    named = api.patch(booking, json={"orderId": free["id"]})
    assert (named.status_code, named.json()["orderId"]) == (200, free["id"])
    assert api.get(f"/api/orders/{free['id']}").json()["bookedAmount"] == "30.00"
    assert titles(fiscalYear=str(year_id)) == ["Altkauf"]
    assert titles(budget=str(budget_id)) == ["Altkauf"]
    assert titles(fiscalYear=str(other_year)) == []
    assert titles(budget=str(other_budget)) == []
    assert titles(budget=str(uuid.uuid4())) == []

    income = api.post(
        "/api/expenses",
        json={
            "amount": "5.00",
            "description": "Pfand",
            "kind": "income",
            "budgetId": str(budget_id),
        },
    ).json()
    refused = api.patch(f"/api/budget-expenses/{income['id']}", json={"orderId": free["id"]})
    assert (refused.status_code, refused.json()["code"]) == (422, "income_without_order")
    direct = api.post(
        "/api/expenses",
        json={
            "amount": "1.00",
            "description": "Porto",
            "budgetId": str(budget_id),
            "orderId": free["id"],
        },
    )
    assert (direct.status_code, direct.json()["orderId"]) == (201, free["id"])
    async with maker() as session:
        service = BudgetTreeService(session)
        with pytest.raises(ValidationProblem):
            await service.update_expense(
                uuid.UUID(income["id"]), ExpenseUpdate(orderId=uuid.UUID(free["id"]))
            )
        with pytest.raises(NotFoundError):
            await service.update_expense(
                uuid.UUID(old.json()["id"]), ExpenseUpdate(orderId=uuid.uuid4())
            )
        kept = await service.update_expense(uuid.UUID(old.json()["id"]), ExpenseUpdate(note="alt"))
        assert kept.order_id == uuid.UUID(free["id"])

    listed = api.get(f"/api/invoices/{invoice_id}/orders").json()["items"]
    assert [(row["accessible"], row["applicationId"]) for row in listed] == [(True, None)]
    blind = _client(migrated, settings, monkeypatch, _BOOK_ONLY)
    assert [
        row["accessible"] for row in blind.get(f"/api/invoices/{invoice_id}/orders").json()["items"]
    ] == [False]

    loose = api.patch(booking, json={"orderId": None})
    assert (loose.status_code, loose.json()["orderId"]) == (200, None)
    entry = (await _audit(maker, "budget_expense_update"))[-1]
    assert (entry.data["before"], entry.data["after"]) == (
        {"order_id": free["id"]},
        {"order_id": None},
    )
    async with maker() as session:
        await RevertService(session).revert(entry.id, "revert-sub", _FINANCE)
        await session.commit()
    assert api.get(f"/api/orders/{free['id']}").json()["bookedAmount"] == "31.00"
    assert (await _audit(maker, "budget_expense_update"))[-1].data["after"] == {
        "order_id": free["id"]
    }
    assert Decimal(api.get(f"/api/orders/{of_antrag['id']}").json()["bookedAmount"]) == 0
