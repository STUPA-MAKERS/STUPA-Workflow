"""Pure tally and result logic, without a database and without a clock.

The module does no I/O, so unit tests cover it fully.

`tally` counts the cast votes per option and finds the leading result.
`result` applies the quorum and the majority rule, and gives passed, rejected or tie.

Decision model (yes and no, with an optional abstention):

YES approves. NO rejects. ABSTAIN abstains.
An abstention never counts toward the majority. It counts toward the quorum only when
`abstainCountsQuorum` is true (default true).
Extra n-options count as cast votes for the quorum and the turnout. They do not count
toward the yes/no majority.

Majority rules on the `yes` and `no` counts. `cast` is every cast vote and `decisive`
is yes plus no.

`simple`: passed at yes > no, tie at yes == no.
`absolute`: absolute majority of every cast vote, `2*yes > cast`, tie at `2*yes == cast`.
`two_thirds`: passed at `3*yes >= 2*decisive`, rejected at `3*no >= 2*decisive`, any
other case is a tie (blocking minority).

`tieBreak` resolves a tie to passed, rejected or tie. A missed quorum always gives
rejected (fail-closed), whatever the majority rule says.

Integer arithmetic avoids float rounding. The percent quorum uses Decimal for exactness.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.shared.config_schemas import Quorum, VoteConfig

YES = "yes"
NO = "no"
ABSTAIN = "abstain"

VoteResult = Literal["passed", "rejected", "tie"]
FailedReason = Literal["quorum", "majority"]


def failed_reason(result: VoteResult, quorum_met: bool) -> FailedReason | None:
    """Give the reason why a vote failed.

    A missed quorum takes precedence over a failed majority. A missed quorum always
    rejects the vote (fail-closed), so it wins.

    Returns:
        `quorum` or `majority` for a rejected result. None for passed and for tie.
    """
    if result != "rejected":
        return None
    return "quorum" if not quorum_met else "majority"


@dataclass(frozen=True, slots=True)
class Outcome:
    """Purely derived result of a tally, with no I/O."""

    result: VoteResult
    quorum_met: bool
    leading: str | None


def tally(options: Iterable[str], choices: Iterable[str | None]) -> dict[str, int]:
    """Count the votes per known option.

    A choice of None and a choice outside the option list do not count.
    """
    counts = {opt: 0 for opt in options}
    for choice in choices:
        if choice is not None and choice in counts:
            counts[choice] += 1
    return counts


def leading(counts: Mapping[str, int]) -> str | None:
    """Find the option with the most votes.

    Returns:
        The leading option. None when no vote exists or when the top is a tie.
    """
    if not counts:
        return None
    top = max(counts.values())
    if top == 0:
        return None
    winners = [opt for opt, n in counts.items() if n == top]
    return winners[0] if len(winners) == 1 else None


def _quorum_met(quorum: Quorum | None, participation: int, eligible: int) -> bool:
    """Check the quorum against the turnout.

    A quorum of None is always met. A percent quorum fails when no voter is eligible
    (fail-closed).
    """
    if quorum is None:
        return True
    value = Decimal(str(quorum.value))
    if quorum.type == "count":
        return Decimal(participation) >= value
    # percent: participation/eligible * 100 >= value  ->  participation*100 >= value*eligible
    if eligible <= 0:
        return False
    return Decimal(participation) * Decimal(100) >= value * Decimal(eligible)


def _majority(rule: str, yes: int, no: int, cast: int) -> VoteResult:
    """Apply the majority rule to the yes and no counts.

    The `two_thirds` rule accepts at a share of 2/3 or more, and rejects symmetrically.
    When neither side reaches 2/3, a blocking minority holds and the result is a tie.

    Returns:
        passed, rejected or tie. A tie here is raw and still needs `tieBreak`.
    """
    if rule == "two_thirds":
        decisive = yes + no
        if decisive == 0:
            return "tie"
        if 3 * yes >= 2 * decisive:
            return "passed"
        if 3 * no >= 2 * decisive:
            return "rejected"
        return "tie"
    threshold = 2 * yes - cast if rule == "absolute" else yes - no
    if threshold > 0:
        return "passed"
    if threshold < 0:
        return "rejected"
    return "tie"


def _resolve_tie(tie_break: str) -> VoteResult:
    """Resolve a raw tie with the `tieBreak` setting."""
    if tie_break == "passed":
        return "passed"
    if tie_break == "rejected":
        return "rejected"
    return "tie"


def result(config: VoteConfig, counts: Mapping[str, int], eligible: int) -> Outcome:
    """Apply the quorum and the majority rule to get the outcome."""
    yes = counts.get(YES, 0)
    no = counts.get(NO, 0)
    abstain = counts.get(ABSTAIN, 0)
    cast = sum(counts.values())

    # Turnout for the quorum counts every cast vote. Abstentions drop out only when
    # `abstainCountsQuorum` is false.
    participation = cast if config.abstain_counts_quorum else cast - abstain
    quorum_met = _quorum_met(config.quorum, participation, eligible)
    lead = leading(counts)

    if not quorum_met:
        return Outcome(result="rejected", quorum_met=False, leading=lead)

    raw = _majority(config.majority_rule, yes, no, cast)
    final: VoteResult = _resolve_tie(config.tie_break) if raw == "tie" else raw
    return Outcome(result=final, quorum_met=True, leading=lead)
