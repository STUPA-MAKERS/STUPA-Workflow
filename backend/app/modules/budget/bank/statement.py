"""Source-agnostic statement data types plus format detection.

Pure functions (no DB/network I/O). Both sources — FinTS fetch (MT940 or CAMT)
and manual file import — end up in the same :class:`StatementLine`.

``amount`` is signed: > 0 income, < 0 expense. The service derives ``kind`` and
``abs(amount)`` for the booking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# Cap = DB column ``numeric(12, 2)`` — reject larger amounts from untrusted
# files cleanly instead of a numeric overflow at INSERT.
_MAX_AMOUNT = Decimal("9999999999.99")


class StatementParseError(ValueError):
    """File is neither valid MT940 nor CAMT (or empty/broken)."""


@dataclass(slots=True)
class StatementLine:
    """One normalized account transaction (source-agnostic)."""

    amount: Decimal  # signed: > 0 income, < 0 expense
    currency: str = "EUR"
    booking_date: date | None = None
    value_date: date | None = None
    purpose: str | None = None
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    end_to_end_id: str | None = None
    reference: str | None = None
    # Bank-assigned unique reference (CAMT ``AcctSvcrRef`` / MT940 ``bank_reference``)
    # — preferred idempotency key; otherwise a content hash (:func:`.dedup.assign_keys`).
    bank_ref: str | None = None
    # Set by the service (after :func:`.dedup.assign_keys`).
    idempotency_key: str = ""
    # Raw fields for traceability (persisted in ``raw_payload``).
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StatementBalance:
    """Closing/account balance of a statement. ``amount`` is signed."""

    amount: Decimal
    currency: str = "EUR"
    as_of: date | None = None


def sane_amount(value: Decimal) -> Decimal:
    """Check the amount for valid range and cent granularity (sign is preserved)."""
    if not value.is_finite() or abs(value) > _MAX_AMOUNT:
        raise StatementParseError(f"amount out of range: {value}")
    # Do NOT silently round sub-cent precision (e.g. CAMT ``100.005``) to 2 places
    # — that would falsify amounts vs. the source; reject clearly.
    if value != value.quantize(Decimal("0.01")):
        raise StatementParseError(f"amount has sub-cent precision: {value}")
    return value


def decode_bytes(data: bytes) -> str:
    """Decode UTF-8 first; latin-1 fallback decodes every byte (no further branch needed)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _looks_like_xml(data: bytes, filename: str | None) -> bool:
    head = data.lstrip()[:512]
    looks_xml = head.startswith(b"<?xml") or (head.startswith(b"<") and b"Document" in data[:4096])
    return looks_xml or (filename or "").lower().endswith(".xml")


def parse_statement(data: bytes, *, filename: str | None = None) -> list[StatementLine]:
    """Parse a statement — format guessed from content (XML vs. not) or extension.

    :raises StatementParseError: neither format matches."""
    return parse_statement_full(data, filename=filename)[0]


def parse_statement_full(
    data: bytes, *, filename: str | None = None
) -> tuple[list[StatementLine], StatementBalance | None]:
    """Like :func:`parse_statement`, additionally returning the closing balance
    if the statement carries one (MT940 ``:62F:`` / CAMT ``CLBD``). Parses once."""
    from app.modules.budget.bank import camt_parse, mt940_parse

    if not data:
        raise StatementParseError("empty file")
    if _looks_like_xml(data, filename):
        lines = camt_parse.parse_camt(data)
        return lines, camt_parse.camt_closing_balance(data)
    return mt940_parse.parse_mt940_full(data)
