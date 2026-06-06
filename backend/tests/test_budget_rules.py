"""TDD: reine Budget-Regeln (T-17) — Stufen, Überbuchung, Auslastung, Zuordbarkeit."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.budget import rules


# ---------------------------------------------------------------- Stufen-Logik
def test_stage_index_and_validity() -> None:
    assert rules.stage_index("requested") == 0
    assert rules.stage_index("paid") == 3
    assert rules.is_valid_stage("reserved")
    assert not rules.is_valid_stage("bogus")


def test_is_committed() -> None:
    assert not rules.is_committed("requested")
    assert rules.is_committed("reserved")
    assert rules.is_committed("approved")
    assert rules.is_committed("paid")


@pytest.mark.parametrize(
    ("current", "target", "expected"),
    [
        ("requested", "reserved", True),
        ("requested", "paid", True),  # Überspringen erlaubt (SDS-A1)
        ("reserved", "reserved", False),  # gleichbleiben → nein
        ("approved", "reserved", False),  # rückwärts → nein
        ("bogus", "paid", False),  # unbekannte Stufe → nein
        ("paid", "bogus", False),
    ],
)
def test_can_advance(current: str, target: str, expected: bool) -> None:
    assert rules.can_advance(current, target) is expected


# ----------------------------------------------------------------- Geld-Logik
def test_as_amount() -> None:
    assert rules.as_amount(None) == Decimal("0")
    assert rules.as_amount(Decimal("12.50")) == Decimal("12.50")


def test_available() -> None:
    assert rules.available(None, Decimal("5")) is None  # unbegrenzt
    assert rules.available(Decimal("100"), Decimal("30")) == Decimal("70")


def test_would_overbook() -> None:
    assert rules.would_overbook(None, Decimal("999"), Decimal("999")) is False
    assert rules.would_overbook(Decimal("100"), Decimal("60"), Decimal("41")) is True
    assert rules.would_overbook(Decimal("100"), Decimal("60"), Decimal("40")) is False
    # None-Betrag zählt als 0 → keine Überbuchung.
    assert rules.would_overbook(Decimal("100"), Decimal("100"), None) is False


# --------------------------------------------------------------- Auslastung
def test_usage_from_stage_sums_full() -> None:
    sums = {
        "requested": Decimal("10"),
        "reserved": Decimal("20"),
        "approved": Decimal("5"),
        "paid": Decimal("15"),
    }
    usage = rules.usage_from_stage_sums(sums, Decimal("100"))
    assert usage.requested == Decimal("10")
    assert usage.committed == Decimal("40")  # 20+5+15
    assert usage.available == Decimal("60")


def test_usage_from_stage_sums_empty_unlimited() -> None:
    usage = rules.usage_from_stage_sums({}, None)
    assert usage.requested == Decimal("0")
    assert usage.committed == Decimal("0")
    assert usage.available is None


def test_stage_sums_by_pot() -> None:
    rows = [
        ("p1", "reserved", Decimal("10")),
        ("p1", "reserved", Decimal("5")),
        ("p1", "paid", Decimal("3")),
        ("p2", "requested", None),
    ]
    out = rules.stage_sums_by_pot(rows)
    assert out["p1"]["reserved"] == Decimal("15")
    assert out["p1"]["paid"] == Decimal("3")
    assert out["p2"]["requested"] == Decimal("0")


# --------------------------------------------------------------- Zuordbarkeit
def test_assignment_block_reason_no_budget() -> None:
    reason = rules.assignment_block_reason(
        has_budget=False, type_gremium_id="g1", pot_gremium_id="g1"
    )
    assert reason is not None and "does not support" in reason


def test_assignment_block_reason_type_without_gremium() -> None:
    reason = rules.assignment_block_reason(
        has_budget=True, type_gremium_id=None, pot_gremium_id="g1"
    )
    assert reason is not None and "gremium" in reason


def test_assignment_block_reason_cross_gremium() -> None:
    reason = rules.assignment_block_reason(
        has_budget=True, type_gremium_id="g1", pot_gremium_id="g2"
    )
    assert reason is not None


def test_assignment_block_reason_ok() -> None:
    assert (
        rules.assignment_block_reason(
            has_budget=True, type_gremium_id="g1", pot_gremium_id="g1"
        )
        is None
    )
