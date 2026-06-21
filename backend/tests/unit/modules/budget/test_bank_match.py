"""Umsatz↔Buchung-Matcher (#fints): Bewertungs-Kaskade. Reine Unit-Tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.budget import bank_match as bm


def _cand(eid: str, amount: str, when: date | None, ref: str | None) -> bm.ExpenseCandidate:
    return bm.ExpenseCandidate(
        expense_id=eid, budget_id="b-" + eid, amount=Decimal(amount), when=when, reference=ref
    )


def test_amount_ref_date_scores_max() -> None:
    cands = [_cand("1", "50.00", date(2024, 1, 2), "RG-42")]
    r = bm.best_match(
        line_amount=Decimal("-50.00"),
        line_when=date(2024, 1, 2),
        line_ref="RG 42",
        line_e2e=None,
        candidates=cands,
    )
    assert r.expense_id == "1"
    assert r.score == 100
    assert "Referenz" in r.reason


def test_amount_and_date_only() -> None:
    cands = [_cand("1", "50.00", date(2024, 1, 3), None)]
    r = bm.best_match(
        line_amount=Decimal("-50.00"),
        line_when=date(2024, 1, 2),
        line_ref=None,
        line_e2e=None,
        candidates=cands,
    )
    assert r.expense_id == "1"
    assert r.score >= bm.SUGGEST_THRESHOLD


def test_amount_far_date_below_threshold() -> None:
    cands = [_cand("1", "50.00", date(2024, 6, 1), None)]
    r = bm.best_match(
        line_amount=Decimal("-50.00"),
        line_when=date(2024, 1, 2),
        line_ref=None,
        line_e2e=None,
        candidates=cands,
    )
    assert r.expense_id is None  # 60 < 70


def test_no_amount_match_returns_empty() -> None:
    cands = [_cand("1", "99.00", date(2024, 1, 2), None)]
    r = bm.best_match(
        line_amount=Decimal("-50.00"),
        line_when=date(2024, 1, 2),
        line_ref=None,
        line_e2e=None,
        candidates=cands,
    )
    assert r.expense_id is None


def test_missing_dates_weak_partial() -> None:
    # Betrag + E2E-Referenz reichen über die Schwelle, auch ohne Datum.
    cands = [_cand("1", "50.00", None, "E2E1")]
    r = bm.best_match(
        line_amount=Decimal("50.00"),
        line_when=None,
        line_ref=None,
        line_e2e="E2E1",
        candidates=cands,
    )
    assert r.expense_id == "1"
    assert r.score >= bm.SUGGEST_THRESHOLD


def test_best_of_several() -> None:
    cands = [
        _cand("near", "50.00", date(2024, 1, 4), None),
        _cand("exact", "50.00", date(2024, 1, 2), "RG-9"),
    ]
    r = bm.best_match(
        line_amount=Decimal("-50.00"),
        line_when=date(2024, 1, 2),
        line_ref="RG9",
        line_e2e=None,
        candidates=cands,
    )
    assert r.expense_id == "exact"
