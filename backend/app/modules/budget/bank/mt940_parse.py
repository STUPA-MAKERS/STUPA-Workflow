"""Convert MT940 statements (``.sta`` or FinTS HKKAZ) to ``statement.StatementLine``.

The module imports ``mt940`` lazily. The library arrives only as a transitive
dependency of ``fints``, and the pure contract path must work without it.
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
    """Parse an MT940 statement (for example a Sparkasse ``.sta``) into lines.

    Raises:
        StatementParseError: The data is unparseable or not MT940.
    """
    return parse_mt940_full(data)[0]


def parse_mt940_full(
    data: bytes,
) -> tuple[list[StatementLine], StatementBalance | None]:
    """Parse like ``parse_mt940`` and also return the closing balance (``:62F:``).

    Returns:
        The lines and the closing balance. The balance is ``None`` when the
        statement carries none.
    """
    import mt940  # lazy import (transitive dependency of fints)

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
    """Convert ``mt940`` transactions into lines.

    The FinTS fetch delivers the same transaction objects. ``parse_mt940`` (file
    import) and the FinTS client (live fetch) share this function, so both paths
    normalize the data in the same way.
    """
    lines: list[StatementLine] = []
    for tx in transactions:  # type: ignore[attr-defined]
        line = _line_from_mt940_data(tx.data)
        if line is not None:
            lines.append(line)
    return lines


def _line_from_mt940_data(d: dict[str, object]) -> StatementLine | None:
    """Map one ``mt940`` transaction ``data`` dict to a ``StatementLine``.

    Returns:
        The line, or ``None`` when the transaction carries no amount.
    """
    amount_obj = d.get("amount")
    magnitude = getattr(amount_obj, "amount", None)
    if magnitude is None:
        return None
    # Derive the sign explicitly from the MT940 status. The ``mt940`` lib negates
    # ONLY on status 'D' and leaves the reversal markers 'RC' and 'RD' positive.
    # A direct-debit return (RC = reversal of a credit = outflow) would otherwise
    # arrive as income. Outflow: D or RC. Income: C or RD. Unknown: keep the sign
    # of the lib.
    raw_amount = Decimal(str(magnitude))
    status = str(d.get("status") or "").upper()
    if status in ("D", "RC"):
        raw_amount = -abs(raw_amount)
    elif status in ("C", "RD"):
        raw_amount = abs(raw_amount)
    amount = sane_amount(raw_amount)
    cp_name, cp_iban = mt940_counterparty(d, credit=raw_amount > 0)
    # Sparkasse MT940 appends the booking time as ``…DATUM dd.mm.yyyy, hh.mm UHR``
    # to the purpose. Detach it and keep the time in ``raw`` for the booking note.
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
    """Map ``mt940.models.Balance`` to ``StatementBalance``.

    The file closing balance and the HKSAL live balance of the client share this
    shape. The ``mt940`` lib already signs the amount through the C/D status.
    """
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
    """Return the MT940 closing balance (``:62F:`` -> ``final_closing_balance``)."""
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
