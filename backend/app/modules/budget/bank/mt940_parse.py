"""MT940 statements (``.sta`` / FinTS HKKAZ) to :class:`~.statement.StatementLine`.

``mt940`` is imported lazily (transitively via ``fints``) so the pure contract
path does not need the lib.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.budget.bank.normalize import (
    clean,
    mt940_counterparty,
    normalize_purpose,
    split_booking_time,
)
from app.modules.budget.bank.statement import (
    StatementBalance,
    StatementLine,
    StatementParseError,
    decode_bytes,
    sane_amount,
)


def parse_mt940(data: bytes) -> list[StatementLine]:
    """Parse an MT940 statement (e.g. Sparkasse ``.sta``) into lines.

    :raises StatementParseError: unparseable / not MT940."""
    return parse_mt940_full(data)[0]


def parse_mt940_full(
    data: bytes,
) -> tuple[list[StatementLine], StatementBalance | None]:
    """Like :func:`parse_mt940`, additionally with the closing balance (``:62F:``), if any."""
    import mt940  # lazy (transitively via fints)

    try:
        transactions = mt940.models.Transactions()
        transactions.parse(decode_bytes(data))
    except Exception as exc:  # pragma: no cover - mt940 raises assorted errors on broken statements
        raise StatementParseError(f"unparseable MT940: {exc}") from exc
    lines = lines_from_mt940_transactions(transactions)
    if not lines:
        raise StatementParseError("MT940 contained no transactions")
    return lines, mt940_closing_balance(transactions)


def lines_from_mt940_transactions(transactions: object) -> list[StatementLine]:
    """Convert ``mt940`` transactions (the FinTS fetch delivers these too) into lines.

    Shared by :func:`parse_mt940` (file import) and the FinTS client (live fetch)
    so both paths normalize identically."""
    lines: list[StatementLine] = []
    for tx in transactions:  # type: ignore[attr-defined]
        line = _line_from_mt940_data(tx.data)
        if line is not None:
            lines.append(line)
    return lines


def _line_from_mt940_data(d: dict[str, object]) -> StatementLine | None:
    """Map one ``mt940`` transaction ``data`` dict to a :class:`StatementLine` (or ``None``)."""
    amount_obj = d.get("amount")
    magnitude = getattr(amount_obj, "amount", None)
    if magnitude is None:
        return None
    # Derive the sign explicitly from the MT940 status: the ``mt940`` lib negates
    # ONLY on status == 'D' and leaves reversal markers 'RC'/'RD' positive — a
    # direct-debit return (RC = reversal of a credit = outflow) would otherwise
    # arrive as income. Outflow: D / RC. Income: C / RD. Unknown: keep lib sign.
    raw_amount = Decimal(str(magnitude))
    status = str(d.get("status") or "").upper()
    if status in ("D", "RC"):
        raw_amount = -abs(raw_amount)
    elif status in ("C", "RD"):
        raw_amount = abs(raw_amount)
    amount = sane_amount(raw_amount)
    cp_name, cp_iban = mt940_counterparty(d, credit=raw_amount > 0)
    # Sparkasse MT940 appends the booking time as ``…DATUM dd.mm.yyyy, hh.mm UHR``
    # to the purpose — detach it and stash the time in ``raw`` for the booking note.
    purpose, booking_time = split_booking_time(normalize_purpose(clean(d.get("purpose"))))
    raw = {k: str(v) for k, v in d.items() if v is not None}
    if booking_time:
        raw["booking_time"] = booking_time
    return StatementLine(
        amount=amount,
        currency=str(getattr(amount_obj, "currency", None) or d.get("currency") or "EUR"),
        booking_date=as_date(d.get("entry_date") or d.get("guessed_entry_date")),
        value_date=as_date(d.get("date")),
        purpose=purpose,
        counterparty_name=cp_name,
        counterparty_iban=cp_iban,
        end_to_end_id=clean(d.get("end_to_end_reference")),
        reference=clean(d.get("customer_reference")),
        bank_ref=clean(d.get("bank_reference")),
        raw=raw,
    )


def balance_from_mt940(bal: object) -> StatementBalance | None:
    """Map ``mt940.models.Balance`` to :class:`StatementBalance` (file closing balance
    and the client's HKSAL live balance share this shape). The ``mt940`` lib
    already signs the amount via the C/D status."""
    amount_obj = getattr(bal, "amount", None)
    magnitude = getattr(amount_obj, "amount", None)
    if magnitude is None:
        return None
    try:
        amount = sane_amount(Decimal(str(magnitude)))
    except StatementParseError:
        return None
    return StatementBalance(
        amount=amount,
        currency=str(getattr(amount_obj, "currency", None) or "EUR"),
        as_of=as_date(getattr(bal, "date", None)),
    )


def mt940_closing_balance(transactions: object) -> StatementBalance | None:
    """MT940 closing balance (``:62F:`` -> ``final_closing_balance``)."""
    data = getattr(transactions, "data", None)
    if not isinstance(data, dict):
        return None
    bal = data.get("final_closing_balance") or data.get("final_opening_balance")
    return balance_from_mt940(bal) if bal is not None else None


def as_date(value: object | None) -> date | None:
    """Defensively convert an mt940 ``Date`` (``datetime.date`` subclass) to ``date``."""
    if value is None:
        return None
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    return None
