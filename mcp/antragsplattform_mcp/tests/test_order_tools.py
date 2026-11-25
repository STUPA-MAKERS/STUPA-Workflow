"""§F/finance/orders/002872: the order tools send the requests of the order routes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tests.test_todo_card_parts import _FakeApi
from antragsplattform_mcp.tools import _common, orders

PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_order_tools_read_create_change_and_delete(fake_api: _FakeApi) -> None:
    """An agent lists, creates, changes and deletes a Bestellung of an Antrag."""
    asyncio.run(orders.order_list("a1"))
    asyncio.run(orders.order_get("o1"))
    asyncio.run(orders.order_create("a1", S.OrderCreate(title="Beamer", positionIds=["p1"])))
    asyncio.run(orders.order_update("o1", S.OrderPatch(version=2, url=None, note="x")))
    asyncio.run(orders.order_set_status("o1", "ordered", 3))
    asyncio.run(orders.order_delete("o1"))
    assert fake_api.calls == [
        ("GET", "/applications/a1/orders", None),
        ("GET", "/orders/o1", None),
        (
            "POST",
            "/applications/a1/orders",
            {"title": "Beamer", "kind": "order", "positionIds": ["p1"]},
        ),
        ("PATCH", "/orders/o1", {"version": 2, "url": None, "note": "x"}),
        ("POST", "/orders/o1/status", {"status": "ordered", "version": 3}),
        ("DELETE", "/orders/o1", None),
    ]


def test_order_create_without_an_antrag_posts_to_the_orders(fake_api: _FakeApi) -> None:
    """§F/finance/orders/003014: no Antrag sends the create to ``POST /orders``."""
    asyncio.run(orders.order_create(None, S.OrderCreate(title="Beamer")))
    assert fake_api.calls == [
        (
            "POST",
            "/orders",
            {"title": "Beamer", "kind": "order", "positionIds": []},
        ),
    ]


def test_order_invoice_tools_set_remove_and_list(fake_api: _FakeApi) -> None:
    """§F/finance/orders/002873 and 002877: the invoice of a Bestellung and its list."""
    asyncio.run(orders.order_set_invoice("o1", "i1", 2))
    asyncio.run(orders.order_set_invoice("o1", None, 3))
    asyncio.run(orders.invoice_orders("i1"))
    assert fake_api.calls == [
        ("PUT", "/orders/o1/invoice", {"invoiceId": "i1", "version": 2}),
        ("PUT", "/orders/o1/invoice", {"invoiceId": None, "version": 3}),
        ("GET", "/invoices/i1/orders", None),
    ]


def test_order_list_tools_send_the_filter(fake_api: _FakeApi) -> None:
    """§F/finance/orders/002883, 002934: the list, the waiting Anträge and the bookings."""
    asyncio.run(orders.order_list_all(segment="open", gremium="g1", q="Beamer", limit=50))
    asyncio.run(orders.order_list_all())
    asyncio.run(orders.order_pending_applications(budget="b1", with_orders=True))
    asyncio.run(orders.order_pending_applications())
    asyncio.run(orders.order_bookings("o1"))
    assert fake_api.calls == [
        ("GET", "/orders", {"segment": "open", "limit": 50, "gremium": "g1", "q": "Beamer"}),
        ("GET", "/orders", {}),
        ("GET", "/orders/pending-applications", {"withOrders": True, "budget": "b1"}),
        ("GET", "/orders/pending-applications", {}),
        ("GET", "/orders/o1/bookings", None),
    ]


def test_export_orders_passes_the_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    """§F/finance/orders/002886: the export takes the filter of the list."""
    seen: dict[str, object] = {}

    async def fake_download(method: str, path: str, target: str, **kw: object) -> dict:
        seen.update(method=method, path=path, target=target, **kw)
        return {}

    monkeypatch.setattr(orders, "download_to", fake_download)
    asyncio.run(orders.export_orders_xlsx("/tmp/x.xlsx", segment="done", kind="outlay"))
    assert seen == {
        "method": "GET",
        "path": "/orders/export.xlsx",
        "target": "/tmp/x.xlsx",
        "overwrite": False,
        "fallback": "bestellungen.xlsx",
        "query": {"segment": "done", "kind": "outlay"},
    }


def test_order_file_tools_list_upload_and_delete(fake_api: _FakeApi, tmp_path: Path) -> None:
    """A Bestellung has files of its own: list, upload from a local file, delete."""
    pdf = tmp_path / "Rechnung.pdf"
    pdf.write_bytes(PDF)
    asyncio.run(orders.order_attachments("o1"))
    asyncio.run(orders.order_attachment_upload("o1", str(pdf)))
    asyncio.run(orders.order_attachment_delete("o1", "f1"))
    assert [(method, path) for method, path, _ in fake_api.calls] == [
        ("GET", "/orders/o1/attachments"),
        ("POST", "/orders/o1/attachments"),
        ("DELETE", "/orders/o1/attachments/f1"),
    ]
