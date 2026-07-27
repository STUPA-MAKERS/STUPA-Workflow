"""Idempotency keys for staged statement lines.

The key decides whether a re-fetched transaction counts as known. Staging then applies
`ON CONFLICT DO NOTHING`. The key prefers the reference that the bank assigned. Without
one it uses a content hash built purely from raw data. That hash is parser-independent,
so a parser improvement never re-imports the same transaction.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal

from app.modules.budget.bank.statement import StatementLine


def canonical_purpose_key(purpose: str | None) -> str:
    """Reduce a purpose to a stable idempotency part.

    The result keeps alphanumeric characters only, in upper case, capped at 140
    characters. It is immune to whitespace and punctuation, so a cosmetic parser
    normalization cannot cause a double import.
    """
    return re.sub(r"[^0-9A-Za-z]+", "", purpose or "").upper()[:140]


# The ?86 raw fields of the `mt940` lib that the counterparty comes from. The dedup MUST
# rest on these raw fields, NOT on the derived counterparty_* columns.
_CP_RAW_KEYS = (
    "applicant_name",
    "recipient_name",
    "applicant_iban",
    "gvc_applicant_iban",
    "deviate_applicant",
    "deviate_recipient",
)


def raw_dedup_base(
    value_date: date | None, amount: Decimal, end_to_end: str | None, raw: object
) -> tuple[str, ...]:
    """Build a stable dedup key from parser-independent values only.

    The key holds the value date, the amount, the E2E reference, the canonical raw
    purpose and the canonical raw counterparty block. A parser improvement never
    changes it, so the same bank transaction never gets a new key. Truly distinct
    payments keep a different raw ?86 block and stay separable.
    """
    d = raw if isinstance(raw, dict) else {}
    cp_blob = " ".join(str(d.get(k) or "") for k in _CP_RAW_KEYS)
    return (
        value_date.isoformat() if value_date else "",
        str(amount),
        end_to_end or "",
        canonical_purpose_key(str(d.get("purpose") or "")),
        canonical_purpose_key(cp_blob),
    )


def assign_keys(account_scope: str, lines: list[StatementLine]) -> None:
    """Assign an idempotency key to every line, in place.

    The key prefers the bank reference (`bank_ref`). Without one it uses a content hash
    of the raw dedup base plus an intraday run index. The run index separates two
    identical transactions inside one import. The E2E reference separates truly
    different payments across imports. `booking_date` is NOT part of the hash on
    purpose. It is null for a pending transaction and set later, which would make the
    same transaction count as two and import it twice.
    """
    seen: dict[tuple[str, ...], int] = {}
    for ln in lines:
        if ln.bank_ref:
            ln.idempotency_key = sha256_hex(f"{account_scope}|ref|{ln.bank_ref}")
            continue
        base = raw_dedup_base(ln.value_date, ln.amount, ln.end_to_end_id, ln.raw)
        seq = seen.get(base, 0)
        seen[base] = seq + 1
        ln.idempotency_key = sha256_hex(f"{account_scope}|{'|'.join(base)}|{seq}")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
