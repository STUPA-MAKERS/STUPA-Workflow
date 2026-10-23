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

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.shared.config_schemas import ElectionConfig, PollConfig, Quorum, VoteConfig

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


# ---------------------------------------------------------------- F2: elections
#
# An election ballot holds the ids of the chosen candidates as a JSON list (``[]`` =
# full abstention). Every seat that the ballot leaves free is one abstention vote: a
# ballot with 1 of 3 votes gives 2 abstentions. The single-candidate ballot is
# ``yes``/``no``/``abstain``, as for a motion.
#
# Result values: ``elected`` (the seats are decided), ``tie`` (a tie at the seat
# boundary that the lot decides), ``rejected`` (quorum missed, or nobody elected).
# ``runoff`` stays readable for the elections that were closed while a tie at the
# boundary of several seats went to a runoff.

ElectionResult = Literal["elected", "runoff", "tie", "rejected"]


def encode_election_choice(candidate_ids: Sequence[str]) -> str:
    """Return the stored form of an election ballot (a JSON list, sorted)."""
    return json.dumps(sorted(candidate_ids), separators=(",", ":"))


def decode_election_choice(raw: str | None) -> list[str] | None:
    """Read a stored election ballot. A value that is not a list of strings gives None."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return list(value)


@dataclass(frozen=True, slots=True)
class ElectionOutcome:
    """Derived result of an election tally, with no I/O."""

    result: ElectionResult
    quorum_met: bool
    # Votes per candidate id. The single-candidate ballot counts ``yes``/``no`` here.
    counts: dict[str, int]
    # Abstention votes (free seats on the ballots, or ``abstain``).
    abstentions: int
    # Cast ballots (turnout).
    ballots: int
    elected: tuple[str, ...] = ()
    # The tie at the seat boundary: the tied candidates and the open seats. With
    # ``result == 'runoff'`` a runoff decides, with ``result == 'tie'`` the lot.
    tied: tuple[str, ...] = ()
    open_seats: int = 0
    yes: int | None = None
    no: int | None = None

    def display_counts(self) -> dict[str, int]:
        """Return the counts for the tally card: per candidate (or Ja/Nein) and abstain."""
        return {**self.counts, "abstain": self.abstentions}


def _yes_no_outcome(
    config: ElectionConfig, choices: Sequence[str | None], eligible: int
) -> ElectionOutcome:
    counts = tally(("yes", "no", "abstain"), choices)
    ballots = sum(counts.values())
    participation = ballots if config.abstain_counts_quorum else ballots - counts["abstain"]
    quorum_met = _quorum_met(config.quorum, participation, eligible)
    elected = quorum_met and counts["yes"] > counts["no"]
    return ElectionOutcome(
        result="elected" if elected else "rejected",
        quorum_met=quorum_met,
        counts={"yes": counts["yes"], "no": counts["no"]},
        abstentions=counts["abstain"],
        ballots=ballots,
        elected=(config.candidates[0].id,) if elected else (),
        yes=counts["yes"],
        no=counts["no"],
    )


def tally_election(
    choices: Iterable[str | None],
    config: ElectionConfig,
    eligible: int,
    *,
    round_: int = 1,
) -> ElectionOutcome:
    """Count an election and find the elected candidates.

    Every stored ballot counts as one ballot. A candidate id that the election does
    not know, a repeated id and a vote beyond the seats do not count (the cast path
    refuses them anyway). Ranking by votes; a candidate needs at least one vote to be
    elected. When more candidates have votes than there are seats, the first
    ``seats`` win, unless a tie crosses the seat boundary: then the candidates above
    the boundary are elected and the lot decides among the tied ones, also with
    several seats (no runoff). A missed quorum elects nobody.
    """
    raw = list(choices)
    if config.yes_no:
        return _yes_no_outcome(config, raw, eligible)
    known = config.candidate_ids
    counts = {cid: 0 for cid in known}
    abstentions = 0
    full_abstentions = 0
    for item in raw:
        picks = [c for c in dict.fromkeys(decode_election_choice(item) or []) if c in counts]
        picks = picks[: config.seats]
        for cid in picks:
            counts[cid] += 1
        abstentions += config.seats - len(picks)
        if not picks:
            full_abstentions += 1
    ballots = len(raw)
    participation = ballots if config.abstain_counts_quorum else ballots - full_abstentions
    quorum_met = _quorum_met(config.quorum, participation, eligible)
    base = {"counts": counts, "abstentions": abstentions, "ballots": ballots}
    if not quorum_met:
        return ElectionOutcome(result="rejected", quorum_met=False, **base)
    # Stable sort: equal votes keep the order of the candidate list.
    ranked = sorted((cid for cid in known if counts[cid] > 0), key=lambda c: -counts[c])
    if len(ranked) <= config.seats:
        result: ElectionResult = "elected" if ranked else "rejected"
        return ElectionOutcome(result=result, quorum_met=True, elected=tuple(ranked), **base)
    boundary = counts[ranked[config.seats - 1]]
    if counts[ranked[config.seats]] < boundary:
        return ElectionOutcome(
            result="elected", quorum_met=True, elected=tuple(ranked[: config.seats]), **base
        )
    above = tuple(c for c in ranked if counts[c] > boundary)
    tied = tuple(c for c in ranked if counts[c] == boundary)
    return ElectionOutcome(
        result="tie",
        quorum_met=True,
        elected=above,
        tied=tied,
        open_seats=config.seats - len(above),
        **base,
    )


def draw_lot(
    among: Sequence[str], seats: int, choose: Callable[[Sequence[str]], str]
) -> list[str]:
    """Draw ``seats`` distinct candidates from ``among`` with ``choose``.

    The caller passes ``secrets.choice``; a test passes a fixed chooser. The draw
    takes one candidate at a time without replacement.
    """
    pool = list(among)
    drawn: list[str] = []
    for _ in range(min(seats, len(pool))):
        pick = choose(pool)
        pool.remove(pick)
        drawn.append(pick)
    return drawn


# ------------------------------------------------------------------- polls
#
# A poll ballot of a single or a multi poll holds the chosen option ids as a JSON list
# (``[]`` = abstention), as an election ballot does. A date poll ballot holds a JSON
# object with one answer per option id: ``yes``, ``maybe`` or ``no``. A poll only
# counts: no quorum, no majority, no tie break.


def encode_poll_answers(answers: Mapping[str, str]) -> str:
    """Return the stored form of a date poll ballot (a JSON object, sorted keys)."""
    return json.dumps(dict(answers), separators=(",", ":"), sort_keys=True)


def decode_poll_answers(raw: str | None) -> dict[str, str] | None:
    """Read a stored date poll ballot. A value that is not an object of texts gives None."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, dict) or not all(isinstance(v, str) for v in value.values()):
        return None
    return {str(k): v for k, v in value.items()}


@dataclass(frozen=True, slots=True)
class PollOutcome:
    """Derived result of a poll tally, with no I/O."""

    # Votes per option id. A date poll counts the Ja answers here.
    counts: dict[str, int]
    # A date poll: the Vielleicht answers per option id. None for the other modes.
    maybe: dict[str, int] | None
    # Ballots without an option (single and multi only).
    abstentions: int
    # Cast ballots (turnout).
    ballots: int
    # The option ids, highest first. Equal options keep the order of the creator.
    order: tuple[str, ...]
    # The options with the most votes ("meiste Stimmen", "bester Termin"): every tied
    # option, none while no option has a vote.
    top: tuple[str, ...]

    def display_counts(self) -> dict[str, int]:
        """Return the counts for the tally card: per option, plus ``abstain`` (no date)."""
        if self.maybe is not None:
            return dict(self.counts)
        return {**self.counts, ABSTAIN: self.abstentions}


def tally_poll(choices: Iterable[str | None], config: PollConfig) -> PollOutcome:
    """Count a poll.

    Every stored ballot counts as one ballot. An unknown option id, a repeated id, a
    pick beyond the limit and an unknown answer do not count (the cast path refuses
    them anyway). A single or multi poll ranks by votes; a date poll ranks by the Ja
    answers, then by Ja plus Vielleicht.
    """
    raw = list(choices)
    known = config.option_ids
    counts = dict.fromkeys(known, 0)
    if config.mode == "date":
        maybe = dict.fromkeys(known, 0)
        for item in raw:
            for oid, answer in (decode_poll_answers(item) or {}).items():
                if oid in counts and answer == YES:
                    counts[oid] += 1
                elif oid in maybe and answer == "maybe":
                    maybe[oid] += 1

        def key(oid: str) -> tuple[int, int]:
            return (counts[oid], counts[oid] + maybe[oid])

        order = tuple(sorted(known, key=lambda oid: (-key(oid)[0], -key(oid)[1])))
        best = key(order[0])
        top = tuple(oid for oid in order if key(oid) == best) if best[1] > 0 else ()
        return PollOutcome(counts, maybe, 0, len(raw), order, top)
    abstentions = 0
    for item in raw:
        picks = [c for c in dict.fromkeys(decode_election_choice(item) or []) if c in counts]
        picks = picks[: config.choice_limit]
        for oid in picks:
            counts[oid] += 1
        if not picks:
            abstentions += 1
    order = tuple(sorted(known, key=lambda oid: -counts[oid]))
    most = counts[order[0]]
    top = tuple(oid for oid in order if counts[oid] == most) if most > 0 else ()
    return PollOutcome(counts, None, abstentions, len(raw), order, top)
