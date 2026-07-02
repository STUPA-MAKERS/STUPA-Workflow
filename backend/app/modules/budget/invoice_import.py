"""ZUGFeRD/Factur-X import.

Reads the embedded CII XML from an invoice PDF and maps the header data onto
:class:`~app.modules.budget.tree_models.Invoice` fields. Pure function (no
storage/DB I/O); ``pycheval`` is imported lazily so it only stays in memory on
the import path. Currencies other than EUR are rejected (DB CHECK
``invoice_currency_eur``).
"""

from __future__ import annotations

import contextlib
import io
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any
from xml.parsers import expat as expat_errors

if TYPE_CHECKING:
    from pycheval import MinimumInvoice

# CII namespaces (CrossIndustryInvoice 100 — ZUGFeRD 2.x / Factur-X).
_NS_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_NS_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
_NS_UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"

# Known filenames of the embedded CII XML (checked case-insensitively).
# pycheval matches only ``factur-x.xml`` and hangs in an endless loop on other
# names, so we fetch the attachment ourselves via pypdf.
_CII_ATTACHMENT_NAMES = (
    "factur-x.xml",  # Factur-X / ZUGFeRD >= 2.1
    "zugferd-invoice.xml",  # ZUGFeRD 2.0
    "xrechnung.xml",  # XRechnung (CII)
    "facturx.xml",
)


class NotZugferdError(ValueError):
    """PDF without a (valid) embedded ZUGFeRD/Factur-X XML.

    The caller then offers manual entry."""


class UnsupportedInvoiceCurrencyError(ValueError):
    """Invoice currency is not EUR — only EUR is supported (DB CHECK)."""

    def __init__(self, currency: str) -> None:
        super().__init__(f"unsupported invoice currency: {currency}")
        self.currency = currency


@dataclass(slots=True)
class ParsedInvoice:
    """Header data read from the ZUGFeRD XML (all amounts in EUR)."""

    number: str | None
    issue_date: date | None
    due_date: date | None
    supplier: str | None
    net_amount: Decimal | None
    tax_amount: Decimal | None
    gross_amount: Decimal
    currency: str


# Upper bound for the embedded (decompressed) CII XML. Real invoices are far
# below (< 1 MB); the cap limits a FlateDecode zip bomb inside a tiny PDF.
_MAX_EMBEDDED_XML_BYTES = 16 * 1024 * 1024  # 16 MiB


def _extract_cii_xml(data: bytes) -> str:
    """Fetch the embedded CII XML from the PDF, robust against the filename.

    Replaces pycheval's ``extract_facturx_from_pdf`` (endless loop on names
    other than ``factur-x.xml``). Reads attachment NAMES cheaply, then
    decompresses exactly one matching attachment. Deliberately avoids
    ``dict(reader.attachments)``: that decompresses ALL embedded streams at
    once, letting a small PDF balloon to hundreds of MB (memory-exhaustion
    DoS). Anything over :data:`_MAX_EMBEDDED_XML_BYTES` is refused.

    Raises:
        NotZugferdError: Unreadable PDF, no embedded XML, or attachment too large.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        # `attachment_list` decompresses NOTHING; `.name` is cheap (name tree only).
        embedded = {emb.name.lower(): emb for emb in reader.attachment_list}
    except Exception as exc:  # pypdf raises assorted error types on broken PDFs
        raise NotZugferdError(f"unreadable PDF: {exc}") from exc

    if not embedded:
        raise NotZugferdError("PDF has no embedded files")

    chosen = next((embedded[n] for n in _CII_ATTACHMENT_NAMES if n in embedded), None)
    if chosen is None:
        # Fallback: any .xml attachment (generators deviate from the known names).
        chosen = next((emb for name, emb in embedded.items() if name.endswith(".xml")), None)
    if chosen is None:
        raise NotZugferdError("no embedded XML invoice found")

    # Check the declared size first, then the actual one — the declared
    # ``/Size`` is untrusted.
    declared = chosen.size
    if declared is not None and declared > _MAX_EMBEDDED_XML_BYTES:
        raise NotZugferdError(f"embedded invoice XML too large ({declared} bytes)")
    try:
        payload = chosen.content  # decompresses ONLY this attachment
    except Exception as exc:  # noqa: BLE001 — LimitReachedError etc. -> not importable
        raise NotZugferdError(f"unreadable embedded XML: {exc}") from exc
    if len(payload) > _MAX_EMBEDDED_XML_BYTES:
        raise NotZugferdError("embedded invoice XML too large")

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("utf-8", "replace")


def parse_zugferd_pdf(data: bytes) -> ParsedInvoice:
    """Extract, parse and map the CII XML from the PDF.

    Raises:
        NotZugferdError: No/invalid Factur-X (including a broken PDF).
        UnsupportedInvoiceCurrencyError: Currency is not EUR.
    """
    import pycheval

    xml = _extract_cii_xml(data)

    try:
        invoice = pycheval.parse_xml(xml)
    except pycheval.FacturXError:
        # pycheval is a strict EN16931 validator; real-world ZUGFeRD PDFs often
        # carry slightly invalid fields we never read. Instead of rejecting the
        # import, read the header data tolerantly from the extracted CII XML.
        return _parse_cii_header(xml)
    return _map(invoice)


# Upper bound for invoice amounts = DB column ``Numeric(12, 2)``. Larger values
# from the untrusted XML would otherwise 500 as a numeric overflow on INSERT.
_MAX_INVOICE_AMOUNT = Decimal("9999999999.99")


def _amount(money: Any | None) -> Decimal | None:
    """Read ``Money.amount`` (Decimal) defensively — ``None`` stays ``None``."""
    return money.amount if money is not None else None


def _sane_amount(value: Decimal | None) -> Decimal | None:
    """Sanitize an optional amount: ``None``/NaN/negative/too large yields ``None``.

    Amounts come from untrusted XML; invalid optional fields (net/tax) are
    dropped rather than blocking the import (gross is checked separately)."""
    if value is None or not value.is_finite() or value < 0 or value > _MAX_INVOICE_AMOUNT:
        return None
    return value


def _require_sane_gross(value: Decimal) -> Decimal:
    """Validate the (required) gross amount range — otherwise not importable.

    ``NotZugferdError`` makes the UI offer manual entry (no 500/DB error)."""
    if not value.is_finite() or value < 0 or value > _MAX_INVOICE_AMOUNT:
        raise NotZugferdError(f"invoice gross amount out of range: {value}")
    return value


def _map(invoice: MinimumInvoice) -> ParsedInvoice:
    currency = (invoice.currency_code or "EUR").upper()
    if currency != "EUR":
        raise UnsupportedInvoiceCurrencyError(currency)

    gross = _amount(invoice.grand_total_amount)
    if gross is None:
        # Without a gross total there is no booking basis — treat as not importable.
        raise NotZugferdError("invoice without grand total amount")
    gross = _require_sane_gross(gross)

    taxes = getattr(invoice, "tax_total_amounts", None) or []
    tax = sum((t.amount for t in taxes), Decimal("0")) if taxes else None

    # ``due_date`` exists only from BASIC profile up (PaymentTerms); MINIMUM lacks it.
    terms = getattr(invoice, "payment_terms", None)
    due = getattr(terms, "due_date", None) if terms is not None else None

    seller = getattr(invoice, "seller", None)
    supplier = getattr(seller, "name", None) if seller is not None else None

    return ParsedInvoice(
        number=invoice.invoice_number,
        issue_date=invoice.invoice_date,
        due_date=due,
        supplier=supplier,
        net_amount=_sane_amount(_amount(getattr(invoice, "tax_basis_total_amount", None))),
        tax_amount=_sane_amount(tax),
        gross_amount=gross,
        currency="EUR",
    )


class _DtdForbiddenError(ValueError):
    """The CII XML contains a DTD/entity declaration — rejected."""


def _forbid_dtd(*_args: object, **_kwargs: object) -> None:
    """expat callback: hard-reject any DOCTYPE/entity declaration.

    Defense in depth: the XML comes from an uploaded, untrusted PDF.
    ``xml.etree`` blocks external entities (no XXE/SSRF) but allows internal
    entity expansion (billion laughs) and DTDs. We forbid DTDs entirely — a
    real CII invoice carries none."""
    raise _DtdForbiddenError("DTD/entity declarations are not allowed in invoice XML")


def _hardened_fromstring(raw: bytes) -> ET.Element:
    """``ET.fromstring`` replacement without DTD/entity expansion (stdlib-only).

    Wires a pyexpat parser onto an :class:`ET.TreeBuilder` with handlers that
    reject any DOCTYPE/entity declaration, so a malicious invoice PDF can
    trigger neither a billion-laughs DoS nor DTD resolution (XXE/SSRF) — like
    ``defusedxml`` without the extra dependency. Namespace-aware so the
    ``{ns}tag`` lookups below keep working.

    Raises:
        _DtdForbiddenError: The XML contains a DTD/entity declaration.
        expat_errors.ExpatError: The XML is not well-formed.
    """
    builder = ET.TreeBuilder()
    parser = expat_errors.ParserCreate(namespace_separator="}")
    # ``StartDoctypeDeclHandler`` fires at ``<!DOCTYPE`` already, ruling out any
    # DTD and thus all entity references/expansions. The entity-decl handlers
    # are defense in depth in case expat changes behavior.
    parser.StartDoctypeDeclHandler = _forbid_dtd
    parser.EntityDeclHandler = _forbid_dtd
    parser.UnparsedEntityDeclHandler = _forbid_dtd
    # Request no external DTDs/parameter entities (no network/FS access).
    with contextlib.suppress(AttributeError, expat_errors.ExpatError):  # pragma: no cover
        parser.UseForeignDTD(False)

    def _start(tag: str, attrs: dict[str, str]) -> None:
        # expat delivers namespaces as ``ns}local`` -> ``{ns}local`` (ET convention).
        builder.start(_to_qname(tag), {_to_qname(k): v for k, v in attrs.items()})

    parser.StartElementHandler = _start
    parser.EndElementHandler = lambda tag: builder.end(_to_qname(tag))
    parser.CharacterDataHandler = builder.data

    try:
        parser.Parse(raw, True)
    except expat_errors.ExpatError as exc:
        # Map onto the ParseError the existing logic expects.
        raise ET.ParseError(str(exc)) from exc
    return builder.close()


def _to_qname(name: str) -> str:
    """Map an expat name (``ns}local``) to ET ``{ns}local`` or plain ``local``."""
    return f"{{{name}" if "}" in name else name


def _qn(ns: str, tag: str) -> str:
    """Qualified ElementTree tag name ``{ns}tag``."""
    return f"{{{ns}}}{tag}"


def _find_text(el: ET.Element | None, path: str) -> str | None:
    """Text at ``path`` (relative to ``el``) — ``None`` if missing/empty."""
    if el is None:
        return None
    found = el.find(path)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def _cii_date(value: str | None) -> date | None:
    """Parse a CII ``DateTimeString`` (format 102 = ``YYYYMMDD``) into a ``date``."""
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _cii_decimal(value: str | None) -> Decimal | None:
    """Parse a CII amount string defensively into ``Decimal`` (``None`` if missing/invalid)."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _parse_cii_header(xml: str | bytes) -> ParsedInvoice:
    """Read header data tolerantly straight from the CII XML (pycheval fallback).

    Reads only the fields the entry dialog pre-fills; contact/payment/line-item
    data is deliberately ignored. Same guarantees as :func:`_map`: non-EUR
    currency errors out, a missing gross total means not importable.

    Raises:
        NotZugferdError: XML unparseable or without a gross total.
        UnsupportedInvoiceCurrencyError: Currency is not EUR.
    """
    # ``ET.fromstring`` rejects unicode strings with an encoding declaration -> bytes.
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    # Untrusted XML from an uploaded PDF: parse via :func:`_hardened_fromstring`,
    # which hard-rejects DTD/entity expansion (billion laughs/XXE).
    try:
        root = _hardened_fromstring(raw)
    except (ET.ParseError, _DtdForbiddenError) as exc:
        raise NotZugferdError(f"unparseable CII XML: {exc}") from exc

    doc = root.find(_qn(_NS_RSM, "ExchangedDocument"))
    number = _find_text(doc, _qn(_NS_RAM, "ID"))
    issue = _cii_date(
        _find_text(doc, f"{_qn(_NS_RAM, 'IssueDateTime')}/{_qn(_NS_UDT, 'DateTimeString')}")
    )

    tx = root.find(_qn(_NS_RSM, "SupplyChainTradeTransaction"))
    agreement = tx.find(_qn(_NS_RAM, "ApplicableHeaderTradeAgreement")) if tx is not None else None
    supplier = _find_text(agreement, f"{_qn(_NS_RAM, 'SellerTradeParty')}/{_qn(_NS_RAM, 'Name')}")

    settlement = (
        tx.find(_qn(_NS_RAM, "ApplicableHeaderTradeSettlement")) if tx is not None else None
    )
    currency = (_find_text(settlement, _qn(_NS_RAM, "InvoiceCurrencyCode")) or "EUR").upper()
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
    gross = _require_sane_gross(gross)

    tax_elems = summation.findall(_qn(_NS_RAM, "TaxTotalAmount")) if summation is not None else []
    tax_values = [_cii_decimal(e.text) for e in tax_elems if e.text and e.text.strip()]
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
        net_amount=_sane_amount(net),
        tax_amount=_sane_amount(tax),
        gross_amount=gross,
        currency="EUR",
    )
