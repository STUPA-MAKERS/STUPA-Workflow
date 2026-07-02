"""MT940-Kontoauszüge (``.sta`` / FinTS-HKKAZ) → :class:`~.statement.StatementLine` (#fints).

``mt940`` wird **lazy** importiert (transitiv über ``fints``), damit der reine
Contract-Pfad die Lib nicht braucht.
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
    """MT940-Kontoauszug (z. B. Sparkasse ``.sta``) → Umsätze.

    :raises StatementParseError: nicht parsebar / kein MT940."""
    return parse_mt940_full(data)[0]


def parse_mt940_full(
    data: bytes,
) -> tuple[list[StatementLine], StatementBalance | None]:
    """Wie :func:`parse_mt940`, zusätzlich mit Schlusssaldo (``:62F:``), falls vorhanden."""
    import mt940  # lazy (transitiv über fints)

    try:
        transactions = mt940.models.Transactions()
        transactions.parse(decode_bytes(data))
    except Exception as exc:  # pragma: no cover - mt940 wirft diverse Fehler bei kaputten Auszügen
        raise StatementParseError(f"unparseable MT940: {exc}") from exc
    lines = lines_from_mt940_transactions(transactions)
    if not lines:
        raise StatementParseError("MT940 contained no transactions")
    return lines, mt940_closing_balance(transactions)


def lines_from_mt940_transactions(transactions: object) -> list[StatementLine]:
    """``mt940``-Transaktionen (auch der FinTS-Abruf liefert diese) → Umsätze.

    Geteilt von :func:`parse_mt940` (Datei-Import) und dem FinTS-Client (Live-Abruf),
    damit beide Pfade identisch normalisieren."""
    lines: list[StatementLine] = []
    for tx in transactions:  # type: ignore[attr-defined]
        line = _line_from_mt940_data(tx.data)
        if line is not None:
            lines.append(line)
    return lines


def _line_from_mt940_data(d: dict[str, object]) -> StatementLine | None:
    """Eine ``mt940``-Transaktions-``data``-Map → :class:`StatementLine` (oder ``None``)."""
    amount_obj = d.get("amount")
    magnitude = getattr(amount_obj, "amount", None)
    if magnitude is None:
        return None
    # Vorzeichen **explizit** aus dem MT940-Status ableiten (#fints-review): die ``mt940``-
    # Lib negiert NUR bei status == 'D', lässt Storno-Marker 'RC'/'RD' aber unverändert
    # positiv → eine Lastschrift-Rückgabe (RC = Storno einer Gutschrift = Abgang) käme sonst
    # als Eingang an. Abgang: D / RC. Eingang: C / RD. Unbekannt → Lib-Vorzeichen behalten.
    raw_amount = Decimal(str(magnitude))
    status = str(d.get("status") or "").upper()
    if status in ("D", "RC"):
        raw_amount = -abs(raw_amount)
    elif status in ("C", "RD"):
        raw_amount = abs(raw_amount)
    amount = sane_amount(raw_amount)
    cp_name, cp_iban = mt940_counterparty(d, credit=raw_amount > 0)
    # Sparkassen-MT940 hängt die Buchungs-Uhrzeit als ``…DATUM dd.mm.yyyy, hh.mm UHR`` an den
    # Verwendungszweck — vom eigentlichen Zweck lösen (sauberer Zweck) und die Zeit für die
    # spätere Buchungs-Anmerkung in ``raw`` ablegen (#fints).
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
    """``mt940.models.Balance`` → :class:`StatementBalance` (Datei-Schlusssaldo **und** der
    HKSAL-Live-Saldo des FinTS-Clients liefern dieselbe Struktur). Die ``mt940``-Lib signiert den
    Betrag bereits über den C/D-Status."""
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
    """MT940-Schlusssaldo (``:62F:`` → ``final_closing_balance``)."""
    data = getattr(transactions, "data", None)
    if not isinstance(data, dict):
        return None
    bal = data.get("final_closing_balance") or data.get("final_opening_balance")
    return balance_from_mt940(bal) if bal is not None else None


def as_date(value: object | None) -> date | None:
    """mt940-``Date`` (``datetime.date``-Subklasse) defensiv → ``date``."""
    if value is None:
        return None
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    return None
