"""Quellen-agnostische Auszug-Datentypen + Format-Erkennung (#fints).

Reine Funktionen (kein DB-/Netz-I/O). Beide Quellen — der FinTS-Abruf (MT940 bzw. CAMT)
**und** der manuelle Datei-Import — münden in dieselbe :class:`StatementLine`, sodass
Matcher/Service quellen-agnostisch bleiben.

``amount`` ist **vorzeichenbehaftet**: > 0 Eingang (income), < 0 Ausgang (expense). Der
Service leitet daraus ``kind`` + ``abs(amount)`` für die Buchung ab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# Obergrenze = DB-Spalte ``numeric(12, 2)`` — größere Beträge aus untrusted Dateien sauber
# abweisen statt numeric-overflow beim INSERT (vgl. invoice_import #sec-audit).
_MAX_AMOUNT = Decimal("9999999999.99")


class StatementParseError(ValueError):
    """Datei ist weder gültiges MT940 noch CAMT (oder leer/kaputt)."""


@dataclass(slots=True)
class StatementLine:
    """Ein normalisierter Kontoumsatz (quellen-agnostisch)."""

    amount: Decimal  # vorzeichenbehaftet: > 0 Eingang, < 0 Ausgang
    currency: str = "EUR"
    booking_date: date | None = None
    value_date: date | None = None
    purpose: str | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    end_to_end_id: str | None = None
    reference: str | None = None
    # Bank-vergebene eindeutige Referenz (CAMT ``AcctSvcrRef`` / MT940 ``bank_reference``)
    # — bevorzugter Idempotenz-Schlüssel; sonst Inhalts-Hash (s. :func:`.dedup.assign_keys`).
    bank_ref: str | None = None
    # Vom Service gesetzt (nach :func:`.dedup.assign_keys`).
    idempotency_key: str = ""
    # Roh-Felder zur Nachvollziehbarkeit (in ``raw_payload`` persistiert).
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StatementBalance:
    """Schluss-/Kontostand eines Auszugs (#fints-konten). ``amount`` vorzeichenbehaftet."""

    amount: Decimal
    currency: str = "EUR"
    as_of: date | None = None


def sane_amount(value: Decimal) -> Decimal:
    """Betrag auf gültigen Bereich + Cent-Granularität prüfen (Vorzeichen bleibt erhalten)."""
    if not value.is_finite() or abs(value) > _MAX_AMOUNT:
        raise StatementParseError(f"amount out of range: {value}")
    # Sub-Cent-Präzision (z. B. CAMT ``100.005``) NICHT still auf 2 Stellen runden — das
    # würde Beträge gegenüber der Quelle verfälschen; klar ablehnen (#fints-review).
    if value != value.quantize(Decimal("0.01")):
        raise StatementParseError(f"amount has sub-cent precision: {value}")
    return value


def decode_bytes(data: bytes) -> str:
    """UTF-8 zuerst; latin-1 als Fallback dekodiert **jedes** Byte (kein weiterer Zweig nötig)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _looks_like_xml(data: bytes, filename: str | None) -> bool:
    head = data.lstrip()[:512]
    looks_xml = head.startswith(b"<?xml") or (head.startswith(b"<") and b"Document" in data[:4096])
    return looks_xml or (filename or "").lower().endswith(".xml")


def parse_statement(data: bytes, *, filename: str | None = None) -> list[StatementLine]:
    """Auszug parsen — Format aus Inhalt (XML vs. nicht-XML) bzw. Endung erraten.

    :raises StatementParseError: keine der beiden Quellen passt."""
    return parse_statement_full(data, filename=filename)[0]


def parse_statement_full(
    data: bytes, *, filename: str | None = None
) -> tuple[list[StatementLine], StatementBalance | None]:
    """Wie :func:`parse_statement`, liefert zusätzlich den **Schlusssaldo** (#fints-konten),
    falls der Auszug einen trägt (MT940 ``:62F:`` / CAMT ``CLBD``). Parst nur einmal."""
    from app.modules.budget.bank import camt_parse, mt940_parse

    if not data:
        raise StatementParseError("empty file")
    if _looks_like_xml(data, filename):
        lines = camt_parse.parse_camt(data)
        return lines, camt_parse.camt_closing_balance(data)
    return mt940_parse.parse_mt940_full(data)
