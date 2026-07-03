"""Pure tallying and result logic (no DB, no time - fully unit-testable).

* ``tally`` counts cast votes per option and finds the leading result.
* ``result`` applies quorum + majority rule -> passed | rejected | tie.

Decision model (Yes/No with optional abstention):
* YES = approval, NO = rejection, ABSTAIN = abstention.
* Abstention never counts toward the majority; it counts toward the quorum only
  when ``abstainCountsQuorum`` (default True).
* Extra n-options count as cast votes (quorum/turnout) but not toward the Yes/No majority.

Majority rules (``yes``/``no`` votes, ``cast`` = all cast, ``decisive = yes + no``):
* ``simple``     - yes > no; tie when yes == no.
* ``absolute``   - absolute majority of all cast: ``2*yes > cast`` (tie at ``2*yes == cast``).
* ``two_thirds`` - accepted at >= 2/3 (``3*yes >= 2*decisive``); symmetrically rejected
  at ``3*no >= 2*decisive``; otherwise a tie (blocking minority).

A tie is resolved via ``tieBreak`` (passed | rejected | tie). A missed quorum is
always ``rejected`` (fail-closed), regardless of the majority.

Integer arithmetic avoids float rounding; the percent quorum uses Decimal for exactness.
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
    """Why the vote failed: ``quorum`` (missed) takes precedence over ``majority``.

    Only meaningful for a rejected result; passed/tie -> None. A missed quorum is
    always rejected (fail-closed), so it wins.
    """
    if result != "rejected":
        return None
    return "quorum" if not quorum_met else "majority"


@dataclass(frozen=True, slots=True)
class Outcome:
    """Result of a tally (purely derived, no I/O)."""

    result: VoteResult
    quorum_met: bool
    leading: str | None


def tally(options: Iterable[str], choices: Iterable[str | None]) -> dict[str, int]:
    """Count votes per known option (unknown/NULL ``choice`` ignored)."""
    counts = {opt: 0 for opt in options}
    for choice in choices:
        if choice is not None and choice in counts:
            counts[choice] += 1
    return counts


def leading(counts: Mapping[str, int]) -> str | None:
    """Leading option, or None (no votes or a tie at the top)."""
    if not counts:
        return None
    top = max(counts.values())
    if top == 0:
        return None
    winners = [opt for opt, n in counts.items() if n == top]
    return winners[0] if len(winners) == 1 else None


def _quorum_met(quorum: Quorum | None, participation: int, eligible: int) -> bool:
    """Check the quorum. None -> met. Percent is fail-closed with no eligible voters."""
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
    """Apply the majority rule to Yes/No -> passed | rejected | tie (raw tie)."""
    if rule == "two_thirds":
        # >= 2/3 counts as accepted; if neither side reaches 2/3 -> tie (blocking minority).
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
    """Resolve a raw tie via ``tieBreak`` (passed | rejected | tie)."""
    if tie_break == "passed":
        return "passed"
    if tie_break == "rejected":
        return "rejected"
    return "tie"


def result(config: VoteConfig, counts: Mapping[str, int], eligible: int) -> Outcome:
    """Apply quorum + majority -> Outcome."""
    yes = counts.get(YES, 0)
    no = counts.get(NO, 0)
    abstain = counts.get(ABSTAIN, 0)
    cast = sum(counts.values())

    # Turnout for the quorum: all cast votes; abstentions only when
    # ``abstainCountsQuorum`` (default True).
    participation = cast if config.abstain_counts_quorum else cast - abstain
    quorum_met = _quorum_met(config.quorum, participation, eligible)
    lead = leading(counts)

    if not quorum_met:
        return Outcome(result="rejected", quorum_met=False, leading=lead)

    raw = _majority(config.majority_rule, yes, no, cast)
    final: VoteResult = _resolve_tie(config.tie_break) if raw == "tie" else raw
    return Outcome(result=final, quorum_met=True, leading=lead)
