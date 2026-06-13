"""ZUGFeRD/Factur-X-Import (#invoices, #15).

Liest das eingebettete CII-XML aus einem Rechnungs-PDF und mappt die Kopfdaten
auf die Felder unserer :class:`~app.modules.budget.tree_models.Invoice`. Reine
Funktion (kein Storage/DB-I/O); ``pycheval`` wird **lazy** importiert — die Lib
liegt nur auf dem Import-Pfad im Speicher (wie openpyxl/minio).

Mapping (CII → Feld): ``invoice_number`` → number, ``invoice_date`` → issueDate,
``payment_terms.due_date`` → dueDate, ``seller.name`` → supplier,
``tax_basis_total_amount`` → net, Σ ``tax_total_amounts`` → tax,
``grand_total_amount`` → gross, ``currency_code`` → currency (≠ EUR ⇒ Fehler,
DB-CHECK ``invoice_currency_eur``).
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pycheval import MinimumInvoice

# CII-Namespaces (CrossIndustryInvoice 100 — ZUGFeRD 2.x / Factur-X).
_NS_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_NS_RAM = (
    "urn:un:unece:uncefact:data:standard:"
    "ReusableAggregateBusinessInformationEntity:100"
)
_NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"

# Bekannte Dateinamen des eingebetteten CII-XML (case-insensitiv geprüft).
# pycheval matcht **nur** ``factur-x.xml`` und hängt sich bei abweichenden Namen
# in einer Endlosschleife auf (``extract_facturx_from_pdf``: ``while doc`` ohne
# Fortschritt). ZUGFeRD 2.0 nutzt z. B. ``zugferd-invoice.xml`` — deshalb holen
# wir den Anhang selbst über pypdf statt pycheval zu vertrauen.
_CII_ATTACHMENT_NAMES = (
    "factur-x.xml",  # Factur-X / ZUGFeRD ≥ 2.1
    "zugferd-invoice.xml",  # ZUGFeRD 2.0
    "xrechnung.xml",  # XRechnung (CII)
    "facturx.xml",
)


class NotZugferdError(ValueError):
    """PDF ohne (gültiges) eingebettetes ZUGFeRD/Factur-X-XML.

    Der Aufrufer bietet dann die manuelle Erfassung an (#invoices)."""


class UnsupportedInvoiceCurrencyError(ValueError):
    """Rechnungswährung ≠ EUR — nur EUR wird unterstützt (DB-CHECK)."""

    def __init__(self, currency: str) -> None:
        super().__init__(f"unsupported invoice currency: {currency}")
        self.currency = currency


@dataclass(slots=True)
class ParsedInvoice:
    """Aus dem ZUGFeRD-XML gelesene Kopfdaten (alle Beträge in EUR)."""

    number: str | None
    issue_date: date | None
    due_date: date | None
    supplier: str | None
    net_amount: Decimal | None
    tax_amount: Decimal | None
    gross_amount: Decimal
    currency: str


def _extract_cii_xml(data: bytes) -> str:
    """Eingebettetes CII-XML aus dem PDF holen — robust gegen den Dateinamen.

    Ersetzt pychevals ``extract_facturx_from_pdf`` (Endlosschleife bei Namen ≠
    ``factur-x.xml``). Sucht den Anhang über die bekannten ZUGFeRD/Factur-X-
    Namen, sonst den ersten ``*.xml``-Anhang.

    :raises NotZugferdError: PDF unlesbar oder ohne eingebettetes XML.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        attachments: dict[str, list[bytes]] = dict(reader.attachments)
    except Exception as exc:  # pypdf wirft diverse Fehlertypen bei kaputten PDFs
        raise NotZugferdError(f"unreadable PDF: {exc}") from exc

    if not attachments:
        raise NotZugferdError("PDF has no embedded files")

    by_lower = {name.lower(): payloads for name, payloads in attachments.items()}
    payload: bytes | None = None
    for known in _CII_ATTACHMENT_NAMES:
        candidates = by_lower.get(known)
        if candidates:
            payload = candidates[0]
            break
    if payload is None:
        # Notnagel: irgendein .xml-Anhang (Generatoren weichen von den Namen ab).
        for name, payloads in attachments.items():
            if name.lower().endswith(".xml") and payloads:
                payload = payloads[0]
                break
    if payload is None:
        raise NotZugferdError("no embedded XML invoice found")

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("utf-8", "replace")


def parse_zugferd_pdf(data: bytes) -> ParsedInvoice:
    """CII-XML aus dem PDF extrahieren, parsen und mappen.

    :raises NotZugferdError: kein/ungültiges Factur-X (auch kaputtes PDF).
    :raises UnsupportedInvoiceCurrencyError: Währung ≠ EUR.
    """
    import pycheval

    xml = _extract_cii_xml(data)

    try:
        invoice = pycheval.parse_xml(xml)
    except pycheval.FacturXError:
        # pycheval ist ein **strenger** EN16931-Validator; reale ZUGFeRD-PDFs
        # (z. B. das verbreitete invoice-portal.de-Beispiel) tragen oft leicht
        # unsaubere Pflicht-/Optionalfelder, die wir gar nicht lesen (E-Mail-
        # ``schemeID``, leere ``IBANID`` …). Statt den Import abzulehnen, lesen
        # wir die Kopfdaten tolerant direkt aus dem bereits extrahierten CII-XML.
        return _parse_cii_header(xml)
    return _map(invoice)


def _amount(money: Any | None) -> Decimal | None:
    """``Money.amount`` (Decimal) defensiv lesen — ``None`` bleibt ``None``."""
    return money.amount if money is not None else None


def _map(invoice: MinimumInvoice) -> ParsedInvoice:
    currency = (invoice.currency_code or "EUR").upper()
    if currency != "EUR":
        raise UnsupportedInvoiceCurrencyError(currency)

    gross = _amount(invoice.grand_total_amount)
    if gross is None:
        # Ohne Bruttosumme fehlt die Buchungsbasis — als nicht-importierbar werten.
        raise NotZugferdError("invoice without grand total amount")

    taxes = getattr(invoice, "tax_total_amounts", None) or []
    tax = sum((t.amount for t in taxes), Decimal("0")) if taxes else None

    # ``due_date`` gibt es erst ab BASIC (PaymentTerms); MINIMUM hat es nicht.
    terms = getattr(invoice, "payment_terms", None)
    due = getattr(terms, "due_date", None) if terms is not None else None

    seller = getattr(invoice, "seller", None)
    supplier = getattr(seller, "name", None) if seller is not None else None

    return ParsedInvoice(
        number=invoice.invoice_number,
        issue_date=invoice.invoice_date,
        due_date=due,
        supplier=supplier,
        net_amount=_amount(getattr(invoice, "tax_basis_total_amount", None)),
        tax_amount=tax,
        gross_amount=gross,
        currency="EUR",
    )


def _qn(ns: str, tag: str) -> str:
    """Qualifizierter ElementTree-Tag-Name ``{ns}tag``."""
    return f"{{{ns}}}{tag}"


def _find_text(el: ET.Element | None, path: str) -> str | None:
    """Text am ``path`` (relativ zu ``el``) — ``None`` bei fehlend/leer."""
    if el is None:
        return None
    found = el.find(path)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def _cii_date(value: str | None) -> date | None:
    """CII-``DateTimeString`` (Format 102 = ``YYYYMMDD``) → ``date``."""
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _cii_decimal(value: str | None) -> Decimal | None:
    """CII-Betragstext defensiv → ``Decimal`` (``None`` bei fehlend/ungültig)."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _parse_cii_header(xml: str | bytes) -> ParsedInvoice:
    """Kopfdaten tolerant direkt aus dem CII-XML lesen (Fallback zu pycheval).

    Liest nur die Felder, die der Erfassungs-Dialog vorbefüllt — Kontakt-/Zahl-
    und Positionsdaten werden bewusst ignoriert. Gleiche Garantien wie :func:`_map`:
    Währung ≠ EUR ⇒ Fehler, fehlende Bruttosumme ⇒ nicht importierbar.

    :raises NotZugferdError: XML nicht parsebar **oder** ohne Bruttosumme.
    :raises UnsupportedInvoiceCurrencyError: Währung ≠ EUR.
    """
    # ``ET.fromstring`` lehnt Unicode-Strings mit Encoding-Deklaration ab → Bytes.
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    try:
        root = ET.fromstring(raw)  # noqa: S314 - vertrauenswürdige Eigen-Extraktion
    except ET.ParseError as exc:
        raise NotZugferdError(f"unparseable CII XML: {exc}") from exc

    doc = root.find(_qn(_NS_RSM, "ExchangedDocument"))
    number = _find_text(doc, _qn(_NS_RAM, "ID"))
    issue = _cii_date(
        _find_text(
            doc, f"{_qn(_NS_RAM, 'IssueDateTime')}/{_qn(_NS_UDT, 'DateTimeString')}"
        )
    )

    tx = root.find(_qn(_NS_RSM, "SupplyChainTradeTransaction"))
    agreement = (
        tx.find(_qn(_NS_RAM, "ApplicableHeaderTradeAgreement"))
        if tx is not None
        else None
    )
    supplier = _find_text(
        agreement, f"{_qn(_NS_RAM, 'SellerTradeParty')}/{_qn(_NS_RAM, 'Name')}"
    )

    settlement = (
        tx.find(_qn(_NS_RAM, "ApplicableHeaderTradeSettlement"))
        if tx is not None
        else None
    )
    currency = (
        _find_text(settlement, _qn(_NS_RAM, "InvoiceCurrencyCode")) or "EUR"
    ).upper()
    if currency != "EUR":
        raise UnsupportedInvoiceCurrencyError(currency)

    summation = (
        settlement.find(_qn(_NS_RAM, "SpecifiedTradeSettlementHeaderMonetarySummation"))
        if settlement is not None
        else None
    )
    net = _cii_decimal(_find_text(summation, _qn(_NS_RAM, "TaxBasisTotalAmount")))
    gross = _cii_decimal(_find_text(summation, _qn(_NS_RAM, "GrandTotalAmount")))
    if gross is None:
        raise NotZugferdError("invoice without grand total amount")

    tax_elems = (
        summation.findall(_qn(_NS_RAM, "TaxTotalAmount"))
        if summation is not None
        else []
    )
    tax_values = [
        _cii_decimal(e.text) for e in tax_elems if e.text and e.text.strip()
    ]
    tax = sum((v for v in tax_values if v is not None), Decimal("0")) if tax_values else None

    due = _cii_date(
        _find_text(
            settlement,
            f"{_qn(_NS_RAM, 'SpecifiedTradePaymentTerms')}/"
            f"{_qn(_NS_RAM, 'DueDateDateTime')}/{_qn(_NS_UDT, 'DateTimeString')}",
        )
    )

    return ParsedInvoice(
        number=number,
        issue_date=issue,
        due_date=due,
        supplier=supplier,
        net_amount=net,
        tax_amount=tax,
        gross_amount=gross,
        currency="EUR",
    )
