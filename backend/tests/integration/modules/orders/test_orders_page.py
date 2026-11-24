"""The page "Bestellungen", the search, the links and the webhook events on a real Postgres.

§ F/finance/orders/002883 the list holds the Bestellungen of the Anträge that the caller
reads as a member. § 002884 the segments. § 002885 the filters and the search. § 002886 the
export. § 002934 the approved Anträge without a Bestellung. § 002887 a Bestellung is a link
end and its delete takes the links. § 002889 the bookings for the list "Verknüpft". § 002890
the global search. § 002891 the webhook events.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import FiscalYear
from app.modules.search.service import SearchService
from app.modules.todos.models import Link
from app.modules.webhooks.models import Webhook, WebhookDelivery
from app.settings import Settings
from tests._support.guest_apps import GuestSeed
from tests.integration.modules.orders.test_orders import (
    _BLIND,
    _FINANCE,
    _LEDGER,
    _MANAGER,
    _READER,
    _antrag,
    _client,
    _cost_centre,
    maker,  # noqa: F401
    seed,  # noqa: F401
    settings,  # noqa: F401
)

pytestmark = pytest.mark.integration

_VIEWER = Principal(
    sub="viewer-sub", roles=["member"], permissions={"application.read", "budget.view"}
)


async def _buyer(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:  # noqa: F811
    """Create the account of a buyer."""
    async with maker() as session:
        row = PrincipalRow(sub=f"buyer-{uuid.uuid4().hex[:8]}", display_name="Lea Hoffmann")
        session.add(row)
        await session.commit()
        return row.id


def _titles(answer: Any) -> list[str]:
    return [item["title"] for item in answer.json()["items"]]


async def test_the_page_lists_filters_and_exports(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 002883 + § 002884 + § 002885 + § 002886: the list, the segments, the filters, the file."""
    api = _client(migrated, settings, monkeypatch, _FINANCE)
    first = await _antrag(maker, seed)
    second = await _antrag(maker, seed)
    budget_id = await _cost_centre(maker, first)
    buyer_id = await _buyer(maker)
    async with maker() as session:
        year_id = await session.scalar(
            select(FiscalYear.id).where(FiscalYear.budget_id == budget_id)
        )

    def create(app_id: uuid.UUID, **body: object) -> Any:
        return api.post(f"/api/applications/{app_id}/orders", json=body).json()

    regal = create(first, title="Regal", plannedAmount="60.00", orderNumber="ON-4711-XK")
    drucker = create(
        first, title="Drucker", kind="outlay", buyerId=str(buyer_id), actualAmount="500.00"
    )
    kabel = create(second, title="Kabel", supplier="Elektro am Campus")

    assert _titles(api.get("/api/orders")) == ["Kabel", "Drucker", "Regal"]
    api.patch(f"/api/orders/{regal['id']}", json={"note": "eilt", "version": 1})
    assert _titles(api.get("/api/orders")) == ["Regal", "Kabel", "Drucker"]

    assert _titles(api.get("/api/orders", params={"budget": str(budget_id)})) == [
        "Regal",
        "Drucker",
    ]
    assert _titles(api.get("/api/orders", params={"fiscalYear": str(year_id)})) == [
        "Regal",
        "Drucker",
    ]
    assert len(_titles(api.get("/api/orders", params={"gremium": str(uuid.uuid4())}))) == 0
    assert _titles(api.get("/api/orders", params={"kind": "outlay"})) == ["Drucker"]
    assert _titles(api.get("/api/orders", params={"buyer": str(buyer_id)})) == ["Drucker"]
    assert _titles(api.get("/api/orders", params={"q": "ON-4711-XK"})) == ["Regal"]
    by_number = api.get("/api/orders", params={"q": kabel["number"]})
    assert _titles(by_number)[0] == "Kabel"

    api.post(f"/api/orders/{drucker['id']}/status", json={"status": "delivered", "version": 1})
    api.post(f"/api/orders/{kabel['id']}/status", json={"status": "cancelled", "version": 1})
    assert _titles(api.get("/api/orders", params={"segment": "open"})) == ["Regal"]
    assert _titles(api.get("/api/orders", params={"segment": "delivered"})) == ["Drucker"]
    assert _titles(api.get("/api/orders", params={"segment": "done"})) == ["Kabel"]
    paid = api.post(
        "/api/expenses",
        json={
            "amount": "500.00",
            "description": "Drucker",
            "applicationId": str(first),
            "orderId": drucker["id"],
        },
    )
    assert paid.status_code == 201
    assert _titles(api.get("/api/orders", params={"segment": "delivered"})) == []
    assert _titles(api.get("/api/orders", params={"segment": "done"})) == ["Kabel", "Drucker"]
    bookings = api.get(f"/api/orders/{drucker['id']}/bookings").json()
    assert [(b["description"], b["amount"]) for b in bookings] == [("Drucker", "500.00")]

    blind = _client(migrated, settings, monkeypatch, _BLIND)
    assert blind.get("/api/orders").json()["total"] == 0
    assert blind.get("/api/orders/pending-applications").json()["total"] == 0
    assert _client(migrated, settings, monkeypatch, _LEDGER).get("/api/orders").json()["total"] == 0
    assert _client(migrated, settings, monkeypatch, _READER).get("/api/orders").status_code == 403
    viewer = _client(migrated, settings, monkeypatch, _VIEWER)
    assert viewer.get("/api/orders").json()["total"] == 3
    assert viewer.get("/api/orders/export.xlsx").status_code == 403
    assert (
        _client(migrated, settings, monkeypatch, _MANAGER)
        .get(f"/api/orders/{drucker['id']}/bookings")
        .status_code
        == 403
    )

    exported = api.get("/api/orders/export.xlsx", params={"kind": "outlay"})
    assert exported.status_code == 200
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert sheet is not None
    rows = [row for row in sheet.iter_rows(values_only=True) if row[1] == "Drucker"]
    assert len(rows) == 1
    assert (rows[0][2], rows[0][3], rows[0][8], rows[0][9]) == (
        "Auslage",
        "Geliefert",
        500,
        500,
    )
    assert rows[0][12] == "Lea Hoffmann"
    async with maker() as session:
        entry = (
            await session.scalars(
                select(AuditEntry)
                .where(AuditEntry.action == "export")
                .order_by(AuditEntry.id.desc())
            )
        ).first()
    assert entry is not None
    assert (entry.target_id, entry.data) == ("bestellungen.xlsx", {"rows": 1})


async def test_the_approved_antraege_without_a_bestellung(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 002934: listed without a Bestellung, gone with one, listed again after its cancel."""
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)

    def pending() -> list[dict[str, Any]]:
        return [
            item
            for item in api.get("/api/orders/pending-applications").json()["items"]
            if item["id"] == str(app_id)
        ]

    listed = pending()
    assert [(row["title"], row["approvedAmount"]) for row in listed] == [
        ("Büroausstattung", "500.00")
    ]
    order = api.post(f"/api/applications/{app_id}/orders", json={"title": "Regal"}).json()
    assert pending() == []
    offered = api.get("/api/orders/pending-applications", params={"withOrders": "true"}).json()
    assert str(app_id) in [item["id"] for item in offered["items"]]
    api.post(f"/api/orders/{order['id']}/status", json={"status": "cancelled", "version": 1})
    assert len(pending()) == 1


async def test_search_links_and_webhooks(
    migrated: tuple[str, str],
    settings: Settings,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    maker: async_sessionmaker[AsyncSession],  # noqa: F811
    seed: GuestSeed,  # noqa: F811
) -> None:
    """§ 002890 the search, § 002887 the link kind, § 002891 the webhook events."""
    async with maker() as session:
        session.add(
            Webhook(
                name="lager",
                url="https://hooks.example.org/lager",
                active=True,
                secret=b"k",
                subscriptions=[
                    {"event": "order.created", "fields": ["number", "title", "status"]},
                    {
                        "event": "order.status_changed",
                        "fields": ["status", "fromStatus", "applicationTitle"],
                    },
                ],
            )
        )
        await session.commit()
    api = _client(migrated, settings, monkeypatch, _MANAGER)
    app_id = await _antrag(maker, seed)
    order = api.post(
        f"/api/applications/{app_id}/orders",
        json={"title": "Beamer", "orderNumber": "TM-2026-4411-QZ"},
    ).json()
    api.post(f"/api/orders/{order['id']}/status", json={"status": "ordered", "version": 1})

    async with maker() as session:
        deliveries = list(
            await session.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at))
        )
        found = await SearchService(session).search("TM-2026-4411-QZ", _MANAGER)
        hidden = await SearchService(session).search("TM-2026-4411-QZ", _BLIND)
    payloads = {d.event: d.payload for d in deliveries}
    assert payloads["order.created"]["data"] == {
        "number": order["number"],
        "title": "Beamer",
        "status": "planned",
    }
    changed = payloads["order.status_changed"]
    assert changed["data"] == {
        "status": "ordered",
        "fromStatus": "planned",
        "applicationTitle": "Büroausstattung",
    }
    assert (changed["orderId"], changed["applicationId"]) == (order["id"], str(app_id))
    hits = [hit for hit in found.hits if hit.kind == "order"]
    assert [(hit.title, hit.url) for hit in hits] == [("Beamer", f"/orders/{order['id']}")]
    assert [hit for hit in hidden.hits if hit.kind == "order"] == []

    ends = {
        "a": {"kind": "order", "id": order["id"]},
        "b": {"kind": "application", "id": str(app_id)},
    }
    reader = _client(migrated, settings, monkeypatch, _READER)
    assert reader.post("/api/links", json=ends).status_code == 403
    linked = api.post("/api/links", json=ends)
    assert linked.status_code == 201
    of_antrag = api.get("/api/links", params={"kind": "application", "id": str(app_id)})
    assert [(row["kind"], row["title"]) for row in of_antrag.json()["links"]] == [
        ("order", "Beamer")
    ]
    targets = api.get("/api/links/targets", params={"q": "TM-2026-4411-QZ", "kind": "order"})
    assert [t["title"] for t in targets.json()] == ["Beamer"]

    assert api.delete(f"/api/orders/{order['id']}").status_code == 204
    async with maker() as session:
        left = await session.scalars(
            select(Link.id).where((Link.a_kind == "order") | (Link.b_kind == "order"))
        )
        assert list(left) == []
