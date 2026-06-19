"""Abgleich Kontoumsatz ↔ bestehende Buchung (#fints-matching) — reine Bewertung.

Liefert für einen Umsatz einen **Vorschlag**, mit welcher bereits erfassten Buchung er
zusammengehört. Verbindlich wird nichts — der Schatzmeister bestätigt im Review-Dialog.
Die DB-Abfragen (Kandidaten, Gegen-IBAN-Gedächtnis) macht der Service; hier nur die
deterministische, testbare Bewertung.

Kaskade (höchste Präzision zuerst):
* **Referenz** — gleiche ``end_to_end_id`` / Belegnummer (exakt nach Normalisierung).
* **Betrag + Datum** — gleicher Betrag, Datum im Fenster (eng = hoch, weit = prüfen).

Schwellen (vgl. #fints-research): ≥ 90 = starker Vorschlag, 70–89 = Vorschlag, < 70 verworfen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Datums-Fenster (Tage) zwischen Umsatz und Buchung: eng (Buchungs-/Wertstellungsversatz)
# vs. großzügig (manuell mit grobem Datum erfasst).
_TIGHT_DAYS = 2
_WIDE_DAYS = 5

# Score-Schwelle, ab der ein Vorschlag überhaupt zurückgegeben wird.
SUGGEST_THRESHOLD = 70


@dataclass(slots=True)
class ExpenseCandidate:
    """Minimal-Sicht einer bestehenden, noch nicht abgeglichenen Buchung."""

    expense_id: object  # UUID
    budget_id: object  # UUID
    amount: Decimal  # immer > 0 (DB-CHECK)
    when: date | None  # payment_date ?? invoice_date ?? created_at-Datum
    reference: str | None  # Belegnummer / Referenz


@dataclass(slots=True)
class MatchResult:
    """Bester Treffer (oder leer): Buchung + Score + Begründung."""

    expense_id: object | None = None
    budget_id: object | None = None
    score: int = 0
    reason: str = ""


def _norm_ref(value: str | None) -> str:
    """Referenz normalisieren: nur alphanumerisch, uppercase (RF-/E2E-tolerant)."""
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _date_score(line_when: date | None, cand_when: date | None) -> tuple[int, str]:
    """Datums-Nähe bewerten (kein Datum auf einer Seite → schwacher Teil-Score)."""
    if line_when is None or cand_when is None:
        return 10, "kein Datum"
    delta = abs((line_when - cand_when).days)
    if delta <= _TIGHT_DAYS:
        return 40, f"Datum ±{delta} T"
    if delta <= _WIDE_DAYS:
        return 25, f"Datum ±{delta} T"
    return 0, f"Datum {delta} T entfernt"


def score_candidate(
    *,
    line_amount: Decimal,
    line_when: date | None,
    line_ref: str | None,
    line_e2e: str | None,
    candidate: ExpenseCandidate,
) -> MatchResult:
    """Einen Kandidaten gegen den Umsatz bewerten. ``line_amount`` vorzeichenbehaftet."""
    # Betrag muss exakt (Beträge in Cent) passen — sonst ist es nicht dieselbe Zahlung.
    if abs(line_amount) != candidate.amount:
        return MatchResult()

    score = 60  # exakter Betrag = solide Basis
    reasons = ["Betrag exakt"]

    refs = {_norm_ref(line_ref), _norm_ref(line_e2e)} - {""}
    cand_ref = _norm_ref(candidate.reference)
    if cand_ref and cand_ref in refs:
        score += 40
        reasons.append("Referenz")

    date_pts, date_reason = _date_score(line_when, candidate.when)
    score += date_pts
    reasons.append(date_reason)

    # Score **ungekappt** zurückgeben → ``best_match`` kann auch bei zwei „vollen"
    # Treffern den präziseren (mit Referenz) wählen; gekappt wird erst der Sieger.
    return MatchResult(
        expense_id=candidate.expense_id,
        budget_id=candidate.budget_id,
        score=score,
        reason=", ".join(reasons),
    )


def best_match(
    *,
    line_amount: Decimal,
    line_when: date | None,
    line_ref: str | None,
    line_e2e: str | None,
    candidates: list[ExpenseCandidate],
) -> MatchResult:
    """Besten Kandidaten über der Schwelle wählen (sonst leeres :class:`MatchResult`)."""
    best = MatchResult()
    for cand in candidates:
        result = score_candidate(
            line_amount=line_amount,
            line_when=line_when,
            line_ref=line_ref,
            line_e2e=line_e2e,
            candidate=cand,
        )
        if result.score > best.score:
            best = result
    if best.score < SUGGEST_THRESHOLD:
        return MatchResult()
    best.score = min(best.score, 100)  # erst der Sieger wird für die Anzeige gekappt
    return best
