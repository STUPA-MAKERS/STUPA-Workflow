"""Idempotenz-Schlüssel für gestagete Umsätze (#fints-dedup, #fints-raw).

Der Schlüssel entscheidet, ob ein erneut abgerufener Umsatz als bekannt gilt
(``ON CONFLICT DO NOTHING`` beim Staging). Bevorzugt wird die bank-vergebene Referenz;
sonst ein Inhalts-Hash **rein aus den Rohdaten** — parser-unabhängig, damit
Parser-Verbesserungen denselben Umsatz nie neu importieren.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal

from app.modules.budget.bank.statement import StatementLine


def canonical_purpose_key(purpose: str | None) -> str:
    """Zweck → stabiler Idempotenz-Bestandteil (#fints-dedup): nur Alphanumerik, großgeschrieben,
    auf 140 Zeichen gekürzt. Unabhängig von Leerzeichen/Interpunktion, damit kosmetische
    Parser-Normalisierungen denselben Umsatz nicht doppelt importieren lassen."""
    return re.sub(r"[^0-9A-Za-z]+", "", purpose or "").upper()[:140]


# ?86-Rohfelder der ``mt940``-Lib, aus denen das Gegenkonto stammt — parser-UNABHÄNGIG (die Lib
# füllt sie aus dem Auszug; unser Code leitet daraus nur die Anzeige ab). Vergleich/Dedup MUSS auf
# diesen Rohfeldern fußen, NICHT auf den abgeleiteten counterparty_*-Spalten (#fints-raw).
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
    """Stabiler Vergleichs-/Dedup-Schlüssel **rein aus parser-unabhängigen Werten** (#fints-raw):
    Wertstellung + Betrag (Fakten) + E2E-Ref + kanonischer Roh-Zweck + kanonischer Roh-Gegenkonto-
    Block. Eine Parser-Verbesserung (IBAN lösen, KRZL verwerfen, Zweck entkleben) ändert ihn NICHT
    mehr → derselbe Bank-Umsatz bekommt nie einen neuen Schlüssel. Echte Einzelzahlungen (anderer
    Auftraggeber/Zweck im Roh-?86) bleiben unterscheidbar."""
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
    """Idempotenz-Schlüssel je Umsatz **in-place** setzen (#fints-research).

    Bevorzugt die bank-vergebene Referenz (``bank_ref``); fehlt sie, ein Inhalts-Hash aus
    (Konto-Scope, **Wertstellung**, Cent-Betrag, Gegen-IBAN, End-to-End-Ref, gekürzter
    Zweck) **plus** einem Intraday-Lauf-Index. Der Lauf-Index trennt zwei *innerhalb eines
    Imports* identische Umsätze; die E2E-Ref trennt genuin verschiedene Zahlungen aus
    *getrennten* Importen. ``booking_date`` ist **bewusst nicht** Teil des Hashes — es ist
    bei vorgemerkten Umsätzen erst null und später gesetzt; sonst gälte derselbe Umsatz
    pending vs. gebucht als zwei verschiedene und würde doppelt importiert.
    """
    seen: dict[tuple[str, ...], int] = {}
    for ln in lines:
        if ln.bank_ref:
            ln.idempotency_key = sha256_hex(f"{account_scope}|ref|{ln.bank_ref}")
            continue
        # Schlüssel rein aus den ROHDATEN (#fints-raw): parser-unabhängig → derselbe Umsatz behält
        # seinen Schlüssel über Parser-Verbesserungen hinweg (keine Re-Import-Dubletten mehr). Der
        # Lauf-Index trennt mehrere im selben Import wirklich identische Roh-Datensätze.
        base = raw_dedup_base(ln.value_date, ln.amount, ln.end_to_end_id, ln.raw)
        seq = seen.get(base, 0)
        seen[base] = seq + 1
        ln.idempotency_key = sha256_hex(f"{account_scope}|{'|'.join(base)}|{seq}")


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
