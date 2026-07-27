"""Pure result() and tally() matrix for the T-15 acceptance criteria.

The matrix covers every majority rule against a met quorum, a missed quorum and a
tie. The tests use no database and no clock, so they stay deterministic.
"""

from __future__ import annotations

import pytest

from app.modules.voting.tally import (
    ABSTAIN,
    NO,
    YES,
    Outcome,
    failed_reason,
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


def test_tally_counts_known_options_ignores_unknown_and_null() -> None:
    counts = tally(OPTIONS, [YES, YES, NO, ABSTAIN, "garbage", None])
    assert counts == {YES: 2, NO: 1, ABSTAIN: 1}


def test_tally_empty() -> None:
    assert tally(OPTIONS, []) == {YES: 0, NO: 0, ABSTAIN: 0}


def test_leading_single_winner() -> None:
    assert leading({YES: 3, NO: 1}) == YES


def test_leading_none_on_empty() -> None:
    assert leading({}) is None


def test_leading_none_when_all_zero() -> None:
    assert leading({YES: 0, NO: 0}) is None


def test_leading_none_on_top_tie() -> None:
    assert leading({YES: 2, NO: 2}) is None


# No quorum is set, so every case here meets the quorum.
@pytest.mark.parametrize(
    ("rule", "counts", "expected"),
    [
        # simple: yes > no / yes < no / tie
        ("simple", {YES: 3, NO: 1}, "passed"),
        ("simple", {YES: 1, NO: 3}, "rejected"),
        ("simple", {YES: 2, NO: 2}, "tie"),
        # absolute: twice the yes count against all cast ballots. An abstention
        # moves the threshold.
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 0}, "passed"),  # 6>4
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 2}, "tie"),     # 6==6
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 3}, "rejected"),  # 6<7
        # Rule two_thirds (≥⅔, R5.1): exactly ⅔ passes. A blocking minority gives a tie.
        ("two_thirds", {YES: 3, NO: 1}, "passed"),   # 9≥8
        ("two_thirds", {YES: 2, NO: 1}, "passed"),   # 6≥6 (exactly ⅔ → passed)
        ("two_thirds", {YES: 1, NO: 2}, "rejected"),  # no reaches ⅔
        ("two_thirds", {YES: 3, NO: 2}, "tie"),      # neither side reaches ⅔ (60%)
        ("two_thirds", {YES: 0, NO: 0}, "tie"),      # no yes or no ballot
    ],
)
def test_majority_rules(rule: str, counts: dict[str, int], expected: str) -> None:
    out = result(_config(majority_rule=rule, tie_break="tie"), counts, eligible=0)
    assert out.result == expected
    assert out.quorum_met is True


@pytest.mark.parametrize(
    ("tie_break", "expected"),
    [("passed", "passed"), ("rejected", "rejected"), ("tie", "tie")],
)
def test_tie_break_resolution(tie_break: str, expected: str) -> None:
    out = result(_config(tie_break=tie_break), {YES: 2, NO: 2}, eligible=0)
    assert out.result == expected


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
    # 5 cast of 10 eligible = 50% ≥ 50%
    out = result(
        _config(quorum={"type": "percent", "value": 50}),
        {YES: 4, NO: 1},
        eligible=10,
    )
    assert out.quorum_met is True


def test_percent_quorum_missed() -> None:
    # 4 cast of 10 = 40% < 50%
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


def test_abstain_counts_toward_quorum_by_default() -> None:
    # 2 yes + 3 abstain = 5 participants ≥ 5
    out = result(
        _config(quorum={"type": "count", "value": 5}),
        {YES: 2, NO: 0, ABSTAIN: 3},
        eligible=10,
    )
    assert out.quorum_met is True


def test_abstain_excluded_from_quorum_when_disabled() -> None:
    # the same ballots, but the abstentions do not count → 2 < 5
    out = result(
        _config(quorum={"type": "count", "value": 5}, abstain_counts_quorum=False),
        {YES: 2, NO: 0, ABSTAIN: 3},
        eligible=10,
    )
    assert out.quorum_met is False


def test_outcome_reports_leading_on_quorum_miss() -> None:
    out = result(
        _config(quorum={"type": "count", "value": 99}), {YES: 3, NO: 1}, eligible=10
    )
    assert out == Outcome(result="rejected", quorum_met=False, leading=YES)


def test_failed_reason_quorum_when_quorum_missed() -> None:
    assert failed_reason("rejected", quorum_met=False) == "quorum"


def test_failed_reason_majority_when_quorum_met_but_rejected() -> None:
    assert failed_reason("rejected", quorum_met=True) == "majority"


def test_failed_reason_none_when_passed_or_tie() -> None:
    assert failed_reason("passed", quorum_met=True) is None
    assert failed_reason("tie", quorum_met=False) is None
