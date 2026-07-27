"""Source-agnostic statement data types plus format detection.

The functions here are pure. They do no database or network I/O. Both sources
end up in the same `StatementLine`: the FinTS fetch (MT940 or CAMT) and the
manual file import.

``amount`` is signed. Above 0 it is income. Below 0 it is an expense. The
service derives ``kind`` and ``abs(amount)`` for the booking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# The cap matches the DB column ``numeric(12, 2)``. A larger amount from an
# untrusted file gets a clean rejection instead of a numeric overflow at INSERT.
_MAX_AMOUNT = Decimal("9999999999.99")


class StatementParseError(ValueError):
    """The file is neither valid MT940 nor valid CAMT, or it is empty or broken."""


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
    # Bank-assigned unique reference (CAMT ``AcctSvcrRef`` / MT940 ``bank_reference``).
    # This is the preferred idempotency key. Without it, `.dedup.assign_keys` falls
    # back to a content hash.
    bank_ref: str | None = None
    # The service sets this after it calls `.dedup.assign_keys`.
    idempotency_key: str = ""
    # Raw fields for traceability. They are stored in ``raw_payload``.
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class StatementBalance:
    """Closing balance of an account statement.

    ``amount`` is signed.
    """

    amount: Decimal
    currency: str = "EUR"
    as_of: date | None = None


def sane_amount(value: Decimal) -> Decimal:
    """Check the amount for a valid range and cent granularity.

    The sign stays as it is.

    Raises:
        StatementParseError: The amount is out of range or has sub-cent precision.
    """
    if not value.is_finite() or abs(value) > _MAX_AMOUNT:
        raise StatementParseError(f"amount out of range: {value}")
    # Do NOT round sub-cent precision (for example CAMT ``100.005``) to 2 places.
    # That would falsify the amount against the source. Reject it instead.
    if value != value.quantize(Decimal("0.01")):
        raise StatementParseError(f"amount has sub-cent precision: {value}")
    return value


def decode_bytes(data: bytes) -> str:
    """Decode the bytes as UTF-8, with latin-1 as the fallback.

    The latin-1 fallback decodes every byte, so no further branch is necessary.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _looks_like_xml(data: bytes, filename: str | None) -> bool:
    head = data.lstrip()[:512]
    looks_xml = head.startswith(b"<?xml") or (head.startswith(b"<") and b"Document" in data[:4096])
    return looks_xml or (filename or "").lower().endswith(".xml")


def parse_statement(data: bytes, *, filename: str | None = None) -> list[StatementLine]:
    """Parse a statement.

    The format comes from the content (XML or not) or from the file extension.

    Raises:
        StatementParseError: Neither format matches.
    """
    return parse_statement_full(data, filename=filename)[0]


def parse_statement_full(
    data: bytes, *, filename: str | None = None
) -> tuple[list[StatementLine], StatementBalance | None]:
    """Parse a statement and also return its closing balance.

    This function works like `parse_statement`. It also returns the closing
    balance when the statement carries one (MT940 ``:62F:`` or CAMT ``CLBD``).
    It parses the input only once.

    Raises:
        StatementParseError: The data is empty or neither format matches.
    """
    from app.modules.budget.bank import camt_parse, mt940_parse

    if not data:
        raise StatementParseError("empty file")
    if _looks_like_xml(data, filename):
        lines = camt_parse.parse_camt(data)
        return lines, camt_parse.camt_closing_balance(data)
    return mt940_parse.parse_mt940_full(data)
