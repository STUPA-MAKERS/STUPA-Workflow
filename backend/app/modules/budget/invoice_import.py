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

# CII-Namespaces (CrossIndustryInvoice 100 — ZUGFeRD 2.x / Factur-X).
_NS_RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
_NS_RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
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


# Obergrenze für das eingebettete (dekomprimierte) CII-XML. Eine echte Rechnung
# liegt weit darunter (< 1 MB); die Schranke begrenzt eine FlateDecode-„Zip-Bomb",
# die in einem ansonsten winzigen PDF eingebettet ist (#sec-audit).
_MAX_EMBEDDED_XML_BYTES = 16 * 1024 * 1024  # 16 MiB


def _extract_cii_xml(data: bytes) -> str:
    """Eingebettetes CII-XML aus dem PDF holen — robust gegen den Dateinamen.

    Ersetzt pychevals ``extract_facturx_from_pdf`` (Endlosschleife bei Namen ≠
    ``factur-x.xml``). Liest die Anhang-NAMEN (billig, ohne Dekompression) und
    dekomprimiert dann **genau einen** passenden Anhang.

    Vermeidet bewusst ``dict(reader.attachments)``: das materialisiert (=
    FlateDecode-dekomprimiert) ALLE eingebetteten Streams auf einmal — ein kleines
    PDF mit vielen komprimierten Anhängen bläht sich so auf hunderte MB auf
    (Speicher-Erschöpfungs-DoS, #sec-audit). pypdf kappt zudem einen einzelnen
    Stream bei 75 MB; wir dekomprimieren ohnehin nur diesen einen Anhang und
    refusen alles über :data:`_MAX_EMBEDDED_XML_BYTES`.

    :raises NotZugferdError: PDF unlesbar, ohne eingebettetes XML oder Anhang zu groß.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        # `attachment_list` dekomprimiert NICHTS; `.name` ist billig (nur Name-Tree).
        embedded = {emb.name.lower(): emb for emb in reader.attachment_list}
    except Exception as exc:  # pypdf wirft diverse Fehlertypen bei kaputten PDFs
        raise NotZugferdError(f"unreadable PDF: {exc}") from exc

    if not embedded:
        raise NotZugferdError("PDF has no embedded files")

    chosen = next((embedded[n] for n in _CII_ATTACHMENT_NAMES if n in embedded), None)
    if chosen is None:
        # Notnagel: irgendein .xml-Anhang (Generatoren weichen von den Namen ab).
        chosen = next((emb for name, emb in embedded.items() if name.endswith(".xml")), None)
    if chosen is None:
        raise NotZugferdError("no embedded XML invoice found")

    # Deklarierte Größe (falls vorhanden) vorab; danach die tatsächliche prüfen
    # (die deklarierte ``/Size`` ist nicht vertrauenswürdig).
    declared = chosen.size
    if declared is not None and declared > _MAX_EMBEDDED_XML_BYTES:
        raise NotZugferdError(f"embedded invoice XML too large ({declared} bytes)")
    try:
        payload = chosen.content  # dekomprimiert NUR diesen Anhang
    except Exception as exc:  # noqa: BLE001 — LimitReachedError u. a. → nicht importierbar
        raise NotZugferdError(f"unreadable embedded XML: {exc}") from exc
    if len(payload) > _MAX_EMBEDDED_XML_BYTES:
        raise NotZugferdError("embedded invoice XML too large")

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


# Obergrenze für Rechnungsbeträge = DB-Spalte ``Numeric(12, 2)``. Werte aus dem
# (untrusted) XML, die das überschreiten, würden sonst beim INSERT als numeric-
# overflow zu einem 500 führen statt sauber abgewiesen zu werden (#sec-audit).
_MAX_INVOICE_AMOUNT = Decimal("9999999999.99")


def _amount(money: Any | None) -> Decimal | None:
    """``Money.amount`` (Decimal) defensiv lesen — ``None`` bleibt ``None``."""
    return money.amount if money is not None else None


def _sane_amount(value: Decimal | None) -> Decimal | None:
    """Optionalen Betrag bereinigen: ``None``/NaN/negativ/zu groß ⇒ ``None``.

    Beträge stammen aus untrusted XML; ungültige optionale Felder (net/tax) werden
    verworfen statt den Import zu blockieren (die Bruttosumme wird separat geprüft)."""
    if value is None or not value.is_finite() or value < 0 or value > _MAX_INVOICE_AMOUNT:
        return None
    return value


def _require_sane_gross(value: Decimal) -> Decimal:
    """Bruttosumme (Pflicht) auf gültigen Bereich prüfen — sonst nicht importierbar.

    ``NotZugferdError`` ⇒ die UI bietet die manuelle Erfassung an (kein 500/DB-Fehler)."""
    if not value.is_finite() or value < 0 or value > _MAX_INVOICE_AMOUNT:
        raise NotZugferdError(f"invoice gross amount out of range: {value}")
    return value


def _map(invoice: MinimumInvoice) -> ParsedInvoice:
    currency = (invoice.currency_code or "EUR").upper()
    if currency != "EUR":
        raise UnsupportedInvoiceCurrencyError(currency)

    gross = _amount(invoice.grand_total_amount)
    if gross is None:
        # Ohne Bruttosumme fehlt die Buchungsbasis — als nicht-importierbar werten.
        raise NotZugferdError("invoice without grand total amount")
    gross = _require_sane_gross(gross)

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
        net_amount=_sane_amount(_amount(getattr(invoice, "tax_basis_total_amount", None))),
        tax_amount=_sane_amount(tax),
        gross_amount=gross,
        currency="EUR",
    )


class _DtdForbiddenError(ValueError):
    """Das CII-XML enthält eine DTD/Entity-Deklaration — wird abgelehnt."""


def _forbid_dtd(*_args: object, **_kwargs: object) -> None:
    """expat-Callback: jede DOCTYPE-/Entity-Deklaration hart ablehnen.

    Defense-in-depth (#sec-audit): das XML stammt aus einem hochgeladenen,
    untrusted PDF. ``xml.etree`` blockt externe Entities (kein XXE/SSRF), lässt
    aber interne Entity-Expansion (Billion-Laughs/quadratic blowup) und DTDs zu.
    Wir verbieten DTDs komplett — eine echte CII-Rechnung trägt keine."""
    raise _DtdForbiddenError("DTD/entity declarations are not allowed in invoice XML")


def _hardened_fromstring(raw: bytes) -> ET.Element:
    """``ET.fromstring``-Ersatz ohne DTD-/Entity-Expansion (stdlib-only Hardening).

    Baut einen pyexpat-Parser direkt auf einen :class:`ET.TreeBuilder` und hängt
    Handler ein, die jede DOCTYPE-/Entity-Deklaration ablehnen. So kann ein
    bösartiges Rechnungs-PDF weder einen Billion-Laughs-DoS noch eine DTD-
    Auflösung (XXE/SSRF) auslösen — vgl. ``defusedxml``, aber ohne Zusatz-
    Abhängigkeit. Namespace-aware (``namespace_separator``) wie ``ET.fromstring``,
    damit die ``{ns}tag``-Lookups unten weiter greifen.

    :raises _DtdForbiddenError: das XML enthält eine DTD/Entity-Deklaration.
    :raises expat_errors.ExpatError: das XML ist nicht wohlgeformt.
    """
    builder = ET.TreeBuilder()
    parser = expat_errors.ParserCreate(namespace_separator="}")
    # ``StartDoctypeDeclHandler`` feuert bereits beim ``<!DOCTYPE`` — damit sind
    # jede DTD und (mangels DTD) alle Entity-Referenzen/-Expansionen ausgeschlossen.
    # Die Entity-Decl-Handler sind Defense-in-depth, falls expat das Verhalten ändert.
    parser.StartDoctypeDeclHandler = _forbid_dtd
    parser.EntityDeclHandler = _forbid_dtd
    parser.UnparsedEntityDeclHandler = _forbid_dtd
    # Keine externen DTDs/Parameter-Entities anfordern (kein Netzwerk/FS-Zugriff).
    with contextlib.suppress(AttributeError, expat_errors.ExpatError):  # pragma: no cover
        parser.UseForeignDTD(False)

    def _start(tag: str, attrs: dict[str, str]) -> None:
        # expat liefert Namespaces als ``ns}local`` → ``{ns}local`` (ET-Konvention).
        builder.start(_to_qname(tag), {_to_qname(k): v for k, v in attrs.items()})

    parser.StartElementHandler = _start
    parser.EndElementHandler = lambda tag: builder.end(_to_qname(tag))
    parser.CharacterDataHandler = builder.data

    try:
        parser.Parse(raw, True)
    except expat_errors.ExpatError as exc:
        # Auf den von der bisherigen Logik erwarteten ParseError abbilden.
        raise ET.ParseError(str(exc)) from exc
    return builder.close()


def _to_qname(name: str) -> str:
    """expat-Name (``ns}local`` bei Namespaces) → ET-``{ns}local`` bzw. ``local``."""
    return f"{{{name}" if "}" in name else name


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
    # Untrusted XML aus hochgeladenem PDF: über :func:`_hardened_fromstring`
    # parsen, das DTD-/Entity-Expansion (Billion-Laughs/XXE) hart ablehnt.
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
