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
            {"title": "Beamer", "kind": "order", "status": "planned", "positionIds": ["p1"]},
        ),
        ("PATCH", "/orders/o1", {"version": 2, "url": None, "note": "x"}),
        ("POST", "/orders/o1/status", {"status": "ordered", "version": 3}),
        ("DELETE", "/orders/o1", None),
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
