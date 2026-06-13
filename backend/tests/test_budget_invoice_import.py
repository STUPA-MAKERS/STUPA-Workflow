"""ZUGFeRD-Import (#invoices, #15): Mapping, Fehlerpfade, Service-Verdrahtung.

Reine Unit-Tests (kein DB/MinIO): das CII-Mapping läuft über ``parse_xml`` von
pycheval; der Service-Pfad nutzt einen Fake-Storage. Der Endpoint (FastAPI) ist im
Router-Contract abgedeckt; hier liegt der Fokus auf Parsing + Speicher-Logik.
"""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal
from typing import Any

import pytest
from pycheval import (
    MinimumInvoice,
    Money,
    PostalAddress,
    TradeParty,
    generate_xml,
    parse_xml,
)
from pycheval.type_codes import DocumentTypeCode
from pypdf import PdfWriter

from app.modules.budget import invoice_import as imp
from app.modules.budget.invoice_import import (
    NotZugferdError,
    ParsedInvoice,
    UnsupportedInvoiceCurrencyError,
)
from app.modules.budget.tree_schemas import InvoiceParseResult
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import load_settings
from app.shared.errors import UnsupportedMediaTypeError


def _minimum_invoice(currency: str = "EUR") -> MinimumInvoice:
    seller = TradeParty("Muster GmbH", PostalAddress(country_code="DE"), vat_id="DE123456789")
    buyer = TradeParty("Studierendenrat", None)
    return MinimumInvoice(
        invoice_number="R-2026-001",
        type_code=DocumentTypeCode.INVOICE,
        invoice_date=dt.date(2026, 6, 13),
        seller=seller,
        buyer=buyer,
        currency_code=currency,
        tax_basis_total_amount=Money("100.00", currency),
        tax_total_amounts=[Money("19.00", currency)],
        grand_total_amount=Money("119.00", currency),
        due_payable_amount=Money("119.00", currency),
    )


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ------------------------------------------------------------------- mapping
def test_map_extracts_header_fields() -> None:
    parsed = imp._map(parse_xml(generate_xml(_minimum_invoice())))
    assert parsed.number == "R-2026-001"
    assert parsed.issue_date == dt.date(2026, 6, 13)
    assert parsed.supplier == "Muster GmbH"
    assert parsed.gross_amount == Decimal("119.00")
    assert parsed.net_amount == Decimal("100.00")
    assert parsed.tax_amount == Decimal("19.00")
    assert parsed.currency == "EUR"


def test_map_rejects_non_eur() -> None:
    invoice = parse_xml(generate_xml(_minimum_invoice(currency="USD")))
    with pytest.raises(UnsupportedInvoiceCurrencyError) as ei:
        imp._map(invoice)
    assert ei.value.currency == "USD"


def test_parse_blank_pdf_is_not_zugferd() -> None:
    with pytest.raises(NotZugferdError):
        imp.parse_zugferd_pdf(_blank_pdf())


def test_parse_garbage_is_not_zugferd() -> None:
    with pytest.raises(NotZugferdError):
        imp.parse_zugferd_pdf(b"definitely not a pdf")


# ------------------------------------------------------------- service path
class _FakeStorage:
    """Erfasst put/remove; liefert eine feste Presign-URL."""

    def __init__(self) -> None:
        self.put_calls: list[tuple[str, bytes, str]] = []
        self.removed: list[str] = []

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.put_calls.append((key, data, content_type))

    async def get(self, key: str) -> bytes:  # pragma: no cover - unused
        return b""

    async def remove(self, key: str) -> None:
        self.removed.append(key)

    def presigned_get_url(self, key: str, **_: Any) -> str:
        return f"https://signed/{key}"


def _service(storage: _FakeStorage) -> BudgetTreeService:
    # parse_invoice_file rührt die Session nicht an → Dummy genügt.
    return BudgetTreeService(object(), storage=storage, settings=load_settings())  # type: ignore[arg-type]


async def test_parse_invoice_file_stores_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _FakeStorage()
    parsed = ParsedInvoice(
        number="R-7",
        issue_date=dt.date(2026, 1, 2),
        due_date=dt.date(2026, 2, 1),
        supplier="ACME",
        net_amount=Decimal("50.00"),
        tax_amount=Decimal("9.50"),
        gross_amount=Decimal("59.50"),
        currency="EUR",
    )
    monkeypatch.setattr(
        "app.modules.budget.tree_service.parse_zugferd_pdf", lambda _data: parsed
    )
    result = await _service(storage).parse_invoice_file(
        _blank_pdf(), filename="rechnung.pdf"
    )
    assert isinstance(result, InvoiceParseResult)
    assert result.gross_amount == Decimal("59.50")
    assert result.supplier == "ACME"
    # Original abgelegt, Token unter dem erwarteten Prefix.
    assert len(storage.put_calls) == 1
    assert result.file_token.startswith("invoices/")
    assert result.file_token == storage.put_calls[0][0]
    assert result.file_mime == "application/pdf"


async def test_parse_invoice_file_rejects_non_pdf() -> None:
    storage = _FakeStorage()
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(storage).parse_invoice_file(b"plain text", filename="x.txt")
    assert storage.put_calls == []


async def test_parse_invoice_file_rejects_non_zugferd_pdf() -> None:
    # Echtes (leeres) PDF, aber ohne Factur-X → kein Objekt abgelegt (kein Waise).
    storage = _FakeStorage()
    with pytest.raises(NotZugferdError):
        await _service(storage).parse_invoice_file(_blank_pdf(), filename="leer.pdf")
    assert storage.put_calls == []
