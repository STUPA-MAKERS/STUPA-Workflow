"""Match a statement line against an existing booking (pure scoring, no DB).

This module produces a suggestion only. The treasurer confirms it in the review
dialog. The service runs the DB queries for the candidates and for the
counterparty-IBAN memory.

The cascade starts with the most precise rule. First comes the reference: the
same ``end_to_end_id`` or receipt number after normalization. Then come the
amount and the date window. A tight window scores high. A wide window needs a
review. A score of 90 or more is a strong suggestion. A score of 70 to 89 is a
suggestion. The code discards a score below 70.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

# Date windows in days between the line and the booking. The tight window covers
# the skew between booking date and value date. The wide window covers a booking
# that a person entered by hand with a rough date.
_TIGHT_DAYS = 2
_WIDE_DAYS = 5

# Minimum score for a suggestion to be returned.
SUGGEST_THRESHOLD = 70


@dataclass(slots=True)
class ExpenseCandidate:
    """Minimal view of an existing, not-yet-reconciled booking."""

    expense_id: object  # UUID
    budget_id: object  # UUID
    amount: Decimal  # always > 0 (DB CHECK)
    when: date | None  # payment_date ?? invoice_date ?? created_at date
    reference: str | None  # receipt number or reference


@dataclass(slots=True)
class MatchResult:
    """Best hit, or an empty result: booking, score and reason."""

    expense_id: object | None = None
    budget_id: object | None = None
    score: int = 0
    reason: str = ""


def _norm_ref(value: str | None) -> str:
    """Normalize a reference: alphanumerics only, uppercase (RF-/E2E-tolerant)."""
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _date_score(line_when: date | None, cand_when: date | None) -> tuple[int, str]:
    """Score date proximity (missing date on either side yields a weak partial score)."""
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
    """Score one candidate against the line.

    ``line_amount`` keeps the sign of the transaction.
    """
    # The amount must match to the cent. Another amount is another payment.
    if abs(line_amount) != candidate.amount:
        return MatchResult()

    score = 60  # base score for an exact amount
    reasons = ["Betrag exakt"]

    refs = {_norm_ref(line_ref), _norm_ref(line_e2e)} - {""}
    cand_ref = _norm_ref(candidate.reference)
    if cand_ref and cand_ref in refs:
        score += 40
        reasons.append("Referenz")

    date_pts, date_reason = _date_score(line_when, candidate.when)
    score += date_pts
    reasons.append(date_reason)

    # Return the score uncapped. ``best_match`` then picks the more precise hit
    # with a reference between two "full" matches. Only the winner is capped.
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
    """Pick the best candidate above the threshold.

    Two bookings with the same top score are ambiguous. The function then makes NO
    suggestion. Otherwise the nondeterministic DB row order would decide which
    booking the code suggests.

    Returns:
        The winning match, or an empty ``MatchResult``.
    """
    scored = [
        score_candidate(
            line_amount=line_amount,
            line_when=line_when,
            line_ref=line_ref,
            line_e2e=line_e2e,
            candidate=cand,
        )
        for cand in candidates
    ]
    real = [r for r in scored if r.expense_id is not None]
    if not real:
        return MatchResult()
    top = max(r.score for r in real)
    if top < SUGGEST_THRESHOLD:
        return MatchResult()
    winners = [r for r in real if r.score == top]
    if len(winners) != 1:
        return MatchResult()  # a tie is ambiguous: no suggestion
    best = winners[0]
    best.score = min(best.score, 100)  # only the winner is capped for display
    return best
