"""Pure result() and tally() matrix for the majority rules.

The matrix covers every majority rule against a met quorum, a missed quorum and a
tie. The tests use no database and no clock, so they stay deterministic.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from app.modules.voting.tally import (
    ABSTAIN,
    NO,
    YES,
    MajorityRule,
    Outcome,
    _majority,
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
    quorum: dict[str, Any] | None = None,
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


@pytest.mark.parametrize(
    ("rule", "counts", "expected"),
    [
        ("simple", {YES: 3, NO: 1}, "passed"),
        ("simple", {YES: 1, NO: 3}, "rejected"),
        ("simple", {YES: 2, NO: 2}, "tie"),
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 0}, "passed"),
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 2}, "tie"),
        ("absolute", {YES: 3, NO: 1, ABSTAIN: 3}, "rejected"),
        ("two_thirds", {YES: 3, NO: 1}, "passed"),
        ("two_thirds", {YES: 2, NO: 1}, "passed"),
        ("two_thirds", {YES: 1, NO: 2}, "rejected"),
        ("two_thirds", {YES: 3, NO: 2}, "tie"),
        ("two_thirds", {YES: 0, NO: 0}, "tie"),
    ],
)
def test_majority_rules(rule: str, counts: dict[str, int], expected: str) -> None:
    """Each majority rule gives the expected result. No quorum is set, so every case meets it.

    ``simple`` compares yes and no. ``absolute`` compares twice the yes count with all
    cast ballots, so an abstention moves the threshold: 6 > 4 passes, 6 == 6 ties, 6 < 7
    rejects. ``two_thirds`` passes at exactly ⅔ (9 ≥ 8, 6 ≥ 6) and rejects when no
    reaches ⅔. A blocking minority (yes at 60 %) or no yes-or-no ballot gives a tie.
    """
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
    """5 cast of 10 eligible = 50% ≥ 50%."""
    out = result(
        _config(quorum={"type": "percent", "value": 50}),
        {YES: 4, NO: 1},
        eligible=10,
    )
    assert out.quorum_met is True


def test_percent_quorum_missed() -> None:
    """4 cast of 10 = 40% < 50%."""
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
    """2 yes + 3 abstain = 5 participants ≥ 5."""
    out = result(
        _config(quorum={"type": "count", "value": 5}),
        {YES: 2, NO: 0, ABSTAIN: 3},
        eligible=10,
    )
    assert out.quorum_met is True


def test_abstain_excluded_from_quorum_when_disabled() -> None:
    """The same ballots without the abstentions give 2 < 5."""
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


def test_majority_refuses_an_unknown_rule() -> None:
    """A rule outside ``MajorityRule`` never gets a result: the match refuses it.

    ``VoteConfig`` validates the rule, so only a bypass of the types reaches this arm.
    """
    with pytest.raises(AssertionError):
        _majority(cast("MajorityRule", "bogus"), 1, 0, 1, 1)


# --- Members rules (§F/meetings/voting/000894, 000895, 000896) ------------------------


@pytest.mark.parametrize(
    ("yes", "no", "abstain", "eligible", "expected"),
    [
        (6, 0, 0, 10, "passed"),
        (5, 0, 0, 10, "rejected"),
        (5, 0, 5, 10, "rejected"),
        (5, 4, 0, 9, "passed"),
        (3, 0, 0, 10, "rejected"),
    ],
)
def test_members_majority_counts_against_the_eligible_count(
    yes: int, no: int, abstain: int, eligible: int, expected: str
) -> None:
    """More than half of the members say yes; an abstention acts as a no (§000894)."""
    out = result(
        _config(majority_rule="members_majority"),
        {YES: yes, NO: no, ABSTAIN: abstain},
        eligible,
    )
    assert out.result == expected


@pytest.mark.parametrize(
    ("yes", "eligible", "expected"),
    [(6, 9, "passed"), (7, 10, "passed"), (6, 10, "rejected"), (2, 3, "passed")],
)
def test_members_two_thirds_is_three_yes_for_two_members(
    yes: int, eligible: int, expected: str
) -> None:
    """The check is ``3 * yes >= 2 * eligible`` (§000895)."""
    out = result(_config(majority_rule="members_two_thirds"), {YES: yes, NO: 0}, eligible)
    assert out.result == expected


@pytest.mark.parametrize("rule", ["members_majority", "members_two_thirds"])
def test_members_rule_without_an_eligible_count_rejects(rule: str) -> None:
    """A count of 0 never passes a motion (§000896)."""
    out = result(_config(majority_rule=rule), {YES: 5, NO: 0}, 0)
    assert out.result == "rejected"


def test_members_rule_has_no_tie() -> None:
    """A members rule gives passed or rejected, so the tie break never applies."""
    config = _config(majority_rule="members_majority", tie_break="passed")
    assert result(config, {YES: 5, NO: 5}, 10).result == "rejected"


def test_members_rule_with_guests_is_refused() -> None:
    """A guest is no member, so the config refuses the pair (§000898)."""
    with pytest.raises(ValueError, match="members rule"):
        VoteConfig.model_validate(
            {"options": OPTIONS, "majorityRule": "members_majority", "guestsVote": True}
        )


# --- Quorum by present persons (§F/meetings/voting/000900, 000901) --------------------


def _present_config(*, percent: int | None = 40, min_present: int | None = None) -> VoteConfig:
    return VoteConfig.model_validate(
        {
            "options": OPTIONS,
            "majorityRule": "simple",
            "quorum": None if percent is None else {"type": "percent", "value": percent},
            "quorumBasis": "present",
            "quorumMinPresent": min_present,
        }
    )


def test_quorum_counts_the_present_persons_and_not_the_ballots() -> None:
    """One ballot of ten members meets a 40 % quorum with four present (§000900)."""
    out = result(_present_config(), {YES: 1, NO: 0}, 10, present=4)
    assert (out.quorum_met, out.result) == (True, "passed")


def test_many_ballots_do_not_replace_present_persons() -> None:
    """Ballots of delegations do not count: three present of ten miss 40 % (§000900)."""
    out = result(_present_config(), {YES: 7, NO: 0}, 10, present=3)
    assert (out.quorum_met, out.result) == (False, "rejected")


def test_a_vote_without_a_meeting_counts_the_ballots() -> None:
    """Without a present count the quorum compares the ballots (§000900)."""
    assert result(_present_config(), {YES: 4, NO: 0}, 10).quorum_met is True
    assert result(_present_config(), {YES: 3, NO: 0}, 10).quorum_met is False


def test_the_basis_ballots_ignores_the_present_count() -> None:
    """A vote that was created before the field keeps the count of its ballots."""
    config = _config(quorum={"type": "percent", "value": 40})
    assert result(config, {YES: 1, NO: 0}, 10, present=9).quorum_met is False


@pytest.mark.parametrize(("present", "met"), [(2, False), (3, True)])
def test_least_number_of_present_persons(present: int, met: bool) -> None:
    """40 % of five is two, and the Gremium still needs three present (§000901)."""
    out = result(_present_config(min_present=3), {YES: 2, NO: 0}, 5, present=present)
    assert out.quorum_met is met


def test_least_number_applies_without_a_percent() -> None:
    """The least number alone can miss the quorum (§000901)."""
    out = result(_present_config(percent=None, min_present=3), {YES: 2, NO: 0}, 5, present=2)
    assert (out.quorum_met, out.result) == (False, "rejected")
