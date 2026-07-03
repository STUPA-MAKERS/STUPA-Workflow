"""Idempotency keys for staged statement lines.

The key decides whether a re-fetched transaction counts as known
(``ON CONFLICT DO NOTHING`` at staging). Prefers the bank-assigned reference;
otherwise a content hash built purely from raw data — parser-independent, so
parser improvements never re-import the same transaction.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal

from app.modules.budget.bank.statement import StatementLine


def canonical_purpose_key(purpose: str | None) -> str:
    """Reduce a purpose to a stable idempotency part: alphanumerics only, uppercased,
    capped at 140 chars — immune to whitespace/punctuation so cosmetic parser
    normalizations cannot cause double imports."""
    return re.sub(r"[^0-9A-Za-z]+", "", purpose or "").upper()[:140]


# ?86 raw fields of the ``mt940`` lib that the counterparty stems from. Dedup MUST
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
    """Stable dedup key built purely from parser-independent values: value date +
    amount + E2E ref + canonical raw purpose + canonical raw counterparty block.
    Parser improvements never change it, so the same bank transaction never gets
    a new key; genuinely distinct payments (different raw ?86) stay separable."""
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
    """Assign idempotency keys per line, in place.

    Prefers the bank reference (``bank_ref``); otherwise a content hash of the
    raw dedup base plus an intraday run index. The run index separates two
    identical transactions within one import; the E2E ref separates genuinely
    different payments across imports. ``booking_date`` is deliberately NOT part
    of the hash — it is null for pending transactions and set later, which would
    make the same transaction count as two and import twice.
    """
    seen: dict[tuple[str, ...], int] = {}
    for ln in lines:
        if ln.bank_ref:
            ln.idempotency_key = sha256_hex(f"{account_scope}|ref|{ln.bank_ref}")
            continue
        # Key purely from RAW data: parser-independent, so a transaction keeps its
        # key across parser improvements (no re-import duplicates). The run index
        # separates truly identical raw records within the same import.
        base = raw_dedup_base(ln.value_date, ln.amount, ln.end_to_end_id, ln.raw)
        seq = seen.get(base, 0)
        seen[base] = seq + 1
        ln.idempotency_key = sha256_hex(f"{account_scope}|{'|'.join(base)}|{seq}")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
