"""ZUGFeRD/Factur-X import.

The module reads the embedded CII XML from an invoice PDF. It maps the header
data onto the fields of `app.modules.budget.tree_models.Invoice`. The functions
are pure and do no storage or database I/O.

The module imports ``pycheval`` lazily, so it stays in memory only on the import
path. The DB CHECK ``invoice_currency_eur`` rejects any currency other than EUR.
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

# Known filenames of the embedded CII XML. The check is case-insensitive.
# pycheval matches only ``factur-x.xml`` and hangs in an endless loop on other
# names, so this module fetches the attachment itself with pypdf.
_CII_ATTACHMENT_NAMES = (
    "factur-x.xml",  # Factur-X / ZUGFeRD >= 2.1
    "zugferd-invoice.xml",  # ZUGFeRD 2.0
    "xrechnung.xml",  # XRechnung (CII)
    "facturx.xml",
)


class NotZugferdError(ValueError):
    """The PDF has no valid embedded ZUGFeRD/Factur-X XML.

    The caller then offers manual entry.
    """


class UnsupportedInvoiceCurrencyError(ValueError):
    """The invoice currency is not EUR.

    The DB CHECK ``invoice_currency_eur`` allows only EUR.
    """

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


# Upper bound for the embedded (decompressed) CII XML. A real invoice stays far
# under this cap, below 1 MB. The cap limits a FlateDecode zip bomb inside a
# tiny PDF.
_MAX_EMBEDDED_XML_BYTES = 16 * 1024 * 1024  # 16 MiB


def _extract_cii_xml(data: bytes) -> str:
    """Fetch the embedded CII XML from the PDF, whatever the attachment is named.

    This function replaces ``extract_facturx_from_pdf`` of pycheval, which loops
    forever on a name other than ``factur-x.xml``. It reads the attachment NAMES
    cheaply, then decompresses exactly one matching attachment.

    The function avoids ``dict(reader.attachments)`` on purpose. That call
    decompresses ALL embedded streams at once. A small PDF can then balloon to
    hundreds of MB, which is a memory-exhaustion DoS.

    Raises:
        NotZugferdError: The PDF is unreadable, has no embedded XML, or the
            attachment is over `_MAX_EMBEDDED_XML_BYTES`.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        # `attachment_list` decompresses NOTHING. `.name` only reads the name tree.
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

    # Check the declared size first, then the actual one. The declared ``/Size``
    # is untrusted.
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
        # pycheval is a strict EN16931 validator. Real ZUGFeRD PDFs often carry
        # slightly invalid fields that this module never reads. So do not reject
        # the file. Read the header data tolerantly from the extracted CII XML.
        return _parse_cii_header(xml)
    return _map(invoice)


# Upper bound for invoice amounts. It matches the DB column ``Numeric(12, 2)``.
# A larger value from the untrusted XML would otherwise raise a 500 as a numeric
# overflow on INSERT.
_MAX_INVOICE_AMOUNT = Decimal("9999999999.99")


def _amount(money: Any | None) -> Decimal | None:
    """Read ``Money.amount`` defensively, keeping ``None`` as ``None``."""
    return money.amount if money is not None else None


def _sane_amount(value: Decimal | None) -> Decimal | None:
    """Sanitize an optional amount.

    The function returns ``None`` for ``None``, for NaN, for a negative value and
    for a value over the cap. Amounts come from untrusted XML. The function drops
    an invalid optional field (net or tax) instead of blocking the import. The
    gross amount has its own check.
    """
    if value is None or not value.is_finite() or value < 0 or value > _MAX_INVOICE_AMOUNT:
        return None
    return value


def _require_sane_gross(value: Decimal) -> Decimal:
    """Validate the range of the required gross amount.

    Raises:
        NotZugferdError: The gross amount is out of range. The UI then offers
            manual entry instead of a 500 or a database error.
    """
    if not value.is_finite() or value < 0 or value > _MAX_INVOICE_AMOUNT:
        raise NotZugferdError(f"invoice gross amount out of range: {value}")
    return value


def _map(invoice: MinimumInvoice) -> ParsedInvoice:
    currency = (invoice.currency_code or "EUR").upper()
    if currency != "EUR":
        raise UnsupportedInvoiceCurrencyError(currency)

    gross = _amount(invoice.grand_total_amount)
    if gross is None:
        # Without a gross total there is no booking basis. Treat it as not importable.
        raise NotZugferdError("invoice without grand total amount")
    gross = _require_sane_gross(gross)

    taxes = getattr(invoice, "tax_total_amounts", None) or []
    tax = sum((t.amount for t in taxes), Decimal("0")) if taxes else None

    # ``due_date`` exists only from the BASIC profile up (PaymentTerms). MINIMUM
    # does not have it.
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
    """The CII XML contains a DTD or entity declaration, which is not allowed."""


def _forbid_dtd(*_args: object, **_kwargs: object) -> None:
    """Reject any DOCTYPE or entity declaration (expat callback).

    This is defense in depth. The XML comes from an uploaded, untrusted PDF.
    ``xml.etree`` blocks external entities, so there is no XXE or SSRF. It still
    allows internal entity expansion (billion laughs) and DTDs. This callback
    forbids DTDs entirely. A real CII invoice carries none.

    Raises:
        _DtdForbiddenError: Always.
    """
    raise _DtdForbiddenError("DTD/entity declarations are not allowed in invoice XML")


def _hardened_fromstring(raw: bytes) -> ET.Element:
    """Replace ``ET.fromstring`` without DTD or entity expansion (stdlib only).

    The function wires a pyexpat parser onto an `ET.TreeBuilder`. The handlers
    reject any DOCTYPE or entity declaration. A malicious invoice PDF can then
    trigger neither a billion-laughs DoS nor DTD resolution (XXE or SSRF). This
    gives what ``defusedxml`` gives, without the extra dependency.

    The parser stays namespace-aware, so the ``{ns}tag`` lookups below keep
    working.

    Raises:
        _DtdForbiddenError: The XML contains a DTD or entity declaration.
        expat_errors.ExpatError: The XML is not well-formed.
    """
    builder = ET.TreeBuilder()
    parser = expat_errors.ParserCreate(namespace_separator="}")
    # ``StartDoctypeDeclHandler`` fires at ``<!DOCTYPE`` already. That rules out
    # any DTD and thus all entity references and expansions. The entity-decl
    # handlers are defense in depth in case expat changes behavior.
    parser.StartDoctypeDeclHandler = _forbid_dtd
    parser.EntityDeclHandler = _forbid_dtd
    parser.UnparsedEntityDeclHandler = _forbid_dtd
    # Request no external DTDs or parameter entities, so no network or FS access.
    with contextlib.suppress(AttributeError, expat_errors.ExpatError):  # pragma: no cover
        parser.UseForeignDTD(False)

    def _start(tag: str, attrs: dict[str, str]) -> None:
        # expat delivers a namespace as ``ns}local``. ET wants ``{ns}local``.
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
    """Return the text at ``path`` relative to ``el``, or ``None`` when missing or empty."""
    if el is None:
        return None
    found = el.find(path)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def _cii_date(value: str | None) -> date | None:
    """Parse a CII ``DateTimeString`` in format 102 (``YYYYMMDD``)."""
    if not value or len(value) < 8 or not value[:8].isdigit():
        return None
    try:
        return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _cii_decimal(value: str | None) -> Decimal | None:
    """Parse a CII amount string defensively, returning ``None`` when missing or invalid."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _parse_cii_header(xml: str | bytes) -> ParsedInvoice:
    """Read header data tolerantly straight from the CII XML (pycheval fallback).

    The function reads only the fields that the entry dialog pre-fills. It
    ignores contact, payment and line-item data on purpose. It gives the same
    guarantees as `_map`. A currency other than EUR is an error. A missing gross
    total means the invoice is not importable.

    Raises:
        NotZugferdError: The XML does not parse or has no gross total.
        UnsupportedInvoiceCurrencyError: The currency is not EUR.
    """
    # ``ET.fromstring`` rejects a unicode string with an encoding declaration.
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    # The XML comes untrusted from an uploaded PDF. `_hardened_fromstring` rejects
    # DTD and entity expansion (billion laughs, XXE).
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
