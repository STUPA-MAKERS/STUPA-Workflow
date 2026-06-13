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


# ------------------------------------------------- tolerant CII fallback (#15)
# Reales CII-XML (Stil invoice-portal.de): die E-Mail trägt kein
# ``schemeID="EM"`` und die ``IBANID`` ist leer — beides lehnt der strenge
# pycheval-Parser ab, obwohl die Datei ein gültiges ZUGFeRD ist. Der tolerante
# Fallback liest die Kopfdaten trotzdem.
_REAL_WORLD_CII = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument>
    <ram:ID>2021_10</ram:ID>
    <ram:IssueDateTime>
      <udt:DateTimeString format="102">20210924</udt:DateTimeString>
    </ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>Webware Internet Solutions GmbH</ram:Name>
        <ram:DefinedTradeContact>
          <ram:EmailURIUniversalCommunication>
            <ram:URIID>johndoe@webware24.de</ram:URIID>
          </ram:EmailURIUniversalCommunication>
        </ram:DefinedTradeContact>
        <ram:URIUniversalCommunication>
          <ram:URIID schemeID="9930">DE319642369</ram:URIID>
        </ram:URIUniversalCommunication>
      </ram:SellerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:PayeePartyCreditorFinancialAccount>
          <ram:IBANID/>
        </ram:PayeePartyCreditorFinancialAccount>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradePaymentTerms>
        <ram:DueDateDateTime>
          <udt:DateTimeString format="102">20211008</udt:DateTimeString>
        </ram:DueDateDateTime>
      </ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>1200.00</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">228.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>1428.00</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""


def test_cii_fallback_reads_header_despite_strict_errors() -> None:
    # pycheval lehnt das XML wegen E-Mail-schemeID/leerer IBAN ab …
    from pycheval.exc import FacturXError

    with pytest.raises(FacturXError):
        parse_xml(_REAL_WORLD_CII)

    # … der tolerante Fallback liefert die Kopfdaten trotzdem korrekt.
    parsed = imp._parse_cii_header(_REAL_WORLD_CII)
    assert parsed.number == "2021_10"
    assert parsed.issue_date == dt.date(2021, 9, 24)
    assert parsed.due_date == dt.date(2021, 10, 8)
    assert parsed.supplier == "Webware Internet Solutions GmbH"
    assert parsed.net_amount == Decimal("1200.00")
    assert parsed.tax_amount == Decimal("228.00")
    assert parsed.gross_amount == Decimal("1428.00")
    assert parsed.currency == "EUR"


def test_cii_fallback_rejects_non_eur() -> None:
    xml = _REAL_WORLD_CII.replace(
        "<ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>",
        "<ram:InvoiceCurrencyCode>USD</ram:InvoiceCurrencyCode>",
    )
    with pytest.raises(UnsupportedInvoiceCurrencyError) as ei:
        imp._parse_cii_header(xml)
    assert ei.value.currency == "USD"


def test_cii_fallback_without_gross_is_not_zugferd() -> None:
    xml = _REAL_WORLD_CII.replace(
        "<ram:GrandTotalAmount>1428.00</ram:GrandTotalAmount>", ""
    )
    with pytest.raises(NotZugferdError):
        imp._parse_cii_header(xml)


def test_cii_fallback_unparseable_is_not_zugferd() -> None:
    with pytest.raises(NotZugferdError):
        imp._parse_cii_header(b"<rsm:CrossIndustryInvoice>not closed")


def test_parse_blank_pdf_is_not_zugferd() -> None:
    with pytest.raises(NotZugferdError):
        imp.parse_zugferd_pdf(_blank_pdf())


def test_parse_garbage_is_not_zugferd() -> None:
    with pytest.raises(NotZugferdError):
        imp.parse_zugferd_pdf(b"definitely not a pdf")


def _pdf_with_xml(name: str, xml: str | bytes) -> bytes:
    """Ein-Seiten-PDF mit dem XML als Anhang ``name`` (für Extractor-Tests)."""
    payload = xml.encode("utf-8") if isinstance(xml, str) else xml
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_attachment(name, payload)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_parse_pdf_with_zugferd20_filename() -> None:
    # ZUGFeRD 2.0 bettet das XML als ``zugferd-invoice.xml`` ein. pychevals
    # ``extract_facturx_from_pdf`` matcht nur ``factur-x.xml`` und lief hier in
    # eine Endlosschleife (Timeout) — unser eigener Extractor liest es korrekt.
    pdf = _pdf_with_xml("zugferd-invoice.xml", generate_xml(_minimum_invoice()))
    parsed = imp.parse_zugferd_pdf(pdf)
    assert parsed.number == "R-2026-001"
    assert parsed.supplier == "Muster GmbH"
    assert parsed.gross_amount == Decimal("119.00")


def test_parse_pdf_with_facturx_filename() -> None:
    pdf = _pdf_with_xml("factur-x.xml", generate_xml(_minimum_invoice()))
    assert imp.parse_zugferd_pdf(pdf).number == "R-2026-001"


def test_extract_picks_xml_attachment_by_extension() -> None:
    # Unbekannter Name, aber ``.xml`` → Notnagel greift.
    pdf = _pdf_with_xml("rechnung_cii.xml", generate_xml(_minimum_invoice()))
    assert imp.parse_zugferd_pdf(pdf).number == "R-2026-001"


def test_extract_without_xml_attachment_is_not_zugferd() -> None:
    pdf = _pdf_with_xml("notes.txt", b"just a note")
    with pytest.raises(NotZugferdError):
        imp.parse_zugferd_pdf(pdf)


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


class _FakeScalars:
    def first(self) -> None:
        return None


class _FakeSession:
    """Minimal-Session: Dubletten-Check (``scalars(...).first()``) liefert None."""

    async def scalars(self, *_a: Any, **_k: Any) -> _FakeScalars:
        return _FakeScalars()


def _service(storage: _FakeStorage) -> BudgetTreeService:
    # parse_invoice_file fragt nur den Dubletten-Check über die Session ab.
    return BudgetTreeService(_FakeSession(), storage=storage, settings=load_settings())  # type: ignore[arg-type]


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
