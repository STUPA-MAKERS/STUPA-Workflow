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
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pycheval import MinimumInvoice


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


def parse_zugferd_pdf(data: bytes) -> ParsedInvoice:
    """CII-XML aus dem PDF extrahieren, parsen und mappen.

    :raises NotZugferdError: kein/ungültiges Factur-X (auch kaputtes PDF).
    :raises UnsupportedInvoiceCurrencyError: Währung ≠ EUR.
    """
    import pycheval
    from pycheval.pdf_extract import extract_facturx_from_pdf

    try:
        # ``extract_facturx_from_pdf`` reicht den Datenstrom an ``pypdf.PdfReader``
        # weiter (akzeptiert BytesIO) — kein Temp-File nötig.
        xml, _relationship = extract_facturx_from_pdf(io.BytesIO(data))
        invoice = pycheval.parse_xml(xml)
    except pycheval.FacturXError as exc:  # Oberklasse aller pycheval-Fehler
        raise NotZugferdError(str(exc)) from exc
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
