"""Reine result()-/tally()-Matrix (T-15 AK: jede Mehrheitsregel × Quorum
erreicht/verfehlt × Patt). Keine DB, keine Zeit — voll deterministisch."""

from __future__ import annotations

import pytest

from app.modules.voting.tally import (
    ABSTAIN,
    NO,
    YES,
    Outcome,
    leading,
    result,
    tally,
)
from app.shared.config_schemas import VoteConfig

OPTIONS = [YES, NO, ABSTAIN]


def _config(
    *,
    majority_rule: str = "simple",
    quorum: dict | None = None,
    abstain_counts_quorum: bool = True,
    tie_break: str = "rejected",
    options: list[str] | None = None,
) -> VoteConfig:
    return VoteConfig.model_validate(
        {
            "options": options or OPTIONS,
            "majorityRule": majority_rule,
            "quorum": quorum,
            "abstainCountsQuorum": abstain_counts_quorum,
            "tieBreak": tie_break,
        }
    )


# --------------------------------------------------------------------------- #
# tally()
# --------------------------------------------------------------------------- #
def test_tally_counts_known_options_ignores_unknown_and_null() -> None:
    counts = tally(OPTIONS, [YES, YES, NO, ABSTAIN, "garbage", None])
    assert counts == {YES: 2, NO: 1, ABSTAIN: 1}


def test_tally_empty() -> None:
    assert tally(OPTIONS, []) == {YES: 0, NO: 0, ABSTAIN: 0}


# --------------------------------------------------------------------------- #
# leading()
# --------------------------------------------------------------------------- #
def test_leading_single_winner() -> None:
    assert leading({YES: 3, NO: 1}) == YES


def test_leading_none_on_empty() -> None:
    assert leading({}) is None


def test_leading_none_when_all_zero() -> None:
    assert leading({YES: 0, NO: 0}) is None


def test_leading_none_on_top_tie() -> None:
    assert leading({YES: 2, NO: 2}) is None


# --------------------------------------------------------------------------- #
# Mehrheitsregel × Patt (Quorum erfüllt, kein Quorum gesetzt)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("rule", "counts", "expected"),
    [
        # simple: Ja > Nein / Ja < Nein / Patt
        ("simple", {YES: 3, NO: 1}, "passed"),
        ("simple", {YES: 1, NO: 3}, "rejected"),
        ("simple", {YES: 2, NO: 2}, "tie"),
        # absolute: 2·yes vs alle abgegebenen (Enthaltung verschiebt die Schwelle)
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 0}, "passed"),  # 6>4
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 2}, "tie"),     # 6==6
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 3}, "rejected"),  # 6<7
        # two_thirds: 3·yes vs 2·(yes+no)
        ("two_thirds", {YES: 3, NO: 1}, "passed"),   # 9>8
        ("two_thirds", {YES: 2, NO: 1}, "tie"),      # 6==6 (genau ⅔)
        ("two_thirds", {YES: 1, NO: 1}, "rejected"),  # 3<4
    ],
)
def test_majority_rules(rule: str, counts: dict[str, int], expected: str) -> None:
    out = result(_config(majority_rule=rule, tie_break="tie"), counts, eligible=0)
    assert out.result == expected
    assert out.quorum_met is True


# --------------------------------------------------------------------------- #
# tieBreak
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("tie_break", "expected"),
    [("passed", "passed"), ("rejected", "rejected"), ("tie", "tie")],
)
def test_tie_break_resolution(tie_break: str, expected: str) -> None:
    out = result(_config(tie_break=tie_break), {YES: 2, NO: 2}, eligible=0)
    assert out.result == expected


# --------------------------------------------------------------------------- #
# Quorum erreicht/verfehlt
# --------------------------------------------------------------------------- #
def test_count_quorum_met_passes() -> None:
    out = result(
        _config(quorum={"type": "count", "value": 3}), {YES: 3, NO: 1}, eligible=10
    )
    assert out.quorum_met is True
    assert out.result == "passed"


def test_count_quorum_missed_rejects_despite_majority() -> None:
    out = result(
        _config(quorum={"type": "count", "value": 7}), {YES: 3, NO: 1}, eligible=10
    )
    assert out.quorum_met is False
    assert out.result == "rejected"


def test_percent_quorum_met() -> None:
    # 5 abgegeben / 10 berechtigt = 50% ≥ 50%
    out = result(
        _config(quorum={"type": "percent", "value": 50}),
        {YES: 4, NO: 1},
        eligible=10,
    )
    assert out.quorum_met is True


def test_percent_quorum_missed() -> None:
    # 4 abgegeben / 10 = 40% < 50%
    out = result(
        _config(quorum={"type": "percent", "value": 50}),
        {YES: 3, NO: 1},
        eligible=10,
    )
    assert out.quorum_met is False
    assert out.result == "rejected"


def test_percent_quorum_no_eligible_fails_closed() -> None:
    out = result(
        _config(quorum={"type": "percent", "value": 1}),
        {YES: 5, NO: 0},
        eligible=0,
    )
    assert out.quorum_met is False


# --------------------------------------------------------------------------- #
# abstainCountsQuorum
# --------------------------------------------------------------------------- #
def test_abstain_counts_toward_quorum_by_default() -> None:
    # 2 Ja + 3 Enthaltung = 5 Beteiligung ≥ 5
    out = result(
        _config(quorum={"type": "count", "value": 5}),
        {YES: 2, NO: 0, ABSTAIN: 3},
        eligible=10,
    )
    assert out.quorum_met is True


def test_abstain_excluded_from_quorum_when_disabled() -> None:
    # gleiche Stimmen, aber Enthaltung zählt nicht → 2 < 5
    out = result(
        _config(quorum={"type": "count", "value": 5}, abstain_counts_quorum=False),
        {YES: 2, NO: 0, ABSTAIN: 3},
        eligible=10,
    )
    assert out.quorum_met is False


# --------------------------------------------------------------------------- #
# Outcome trägt leading auch bei verfehltem Quorum
# --------------------------------------------------------------------------- #
def test_outcome_reports_leading_on_quorum_miss() -> None:
    out = result(
        _config(quorum={"type": "count", "value": 99}), {YES: 3, NO: 1}, eligible=10
    )
    assert out == Outcome(result="rejected", quorum_met=False, leading=YES)
