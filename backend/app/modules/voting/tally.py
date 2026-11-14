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
`members_majority`: passed at `2*yes > eligible`, else rejected.
`members_two_thirds`: passed at `3*yes >= 2*eligible`, else rejected.
The two members rules count against the eligible count of the vote, so an abstention
and a missing ballot have the effect of a no ballot. They have no tie, and without an
eligible count they reject (fail-closed).

Quorum: a vote with `quorumBasis = present` (a meeting vote) compares the present persons
of the roster with the eligible count, and `quorumMinPresent` asks for a least number of
them. Each other vote compares the cast ballots.

`tieBreak` resolves a tie to passed, rejected or tie. A missed quorum always gives
rejected (fail-closed), whatever the majority rule says.

Integer arithmetic avoids float rounding. The percent quorum uses Decimal for exactness.

Elections: an election ballot holds the ids of the chosen candidates as a JSON list
(``[]`` is a full abstention). Every seat that the ballot leaves free is one abstention
vote: a ballot with 1 of 3 votes gives 2 abstentions. The single-candidate ballot is
``yes``/``no``/``abstain``, as for a motion. The results are ``elected`` (the seats are
decided), ``tie`` (a tie at the seat boundary that the lot decides) and ``rejected``
(quorum missed, or nobody elected). ``runoff`` stays readable for the elections that
went to a runoff for a tie at the boundary of several seats.

Polls: a single or multi poll ballot holds the chosen option ids as a JSON list (``[]``
is an abstention), as an election ballot does. A date poll ballot holds a JSON object
with one answer per option id: ``yes``, ``maybe`` or ``no``. A poll only counts: no
quorum, no majority, no tie break.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal, assert_never

from app.shared.config_schemas import (
    ElectionConfig,
    MajorityRule,
    PollConfig,
    Quorum,
    QuorumBasis,
    VoteConfig,
)

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
    return None if result != "rejected" else ("majority" if quorum_met else "quorum")


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
    keys = tuple(dict.fromkeys(options))
    hits = Counter(choices)
    return {opt: hits[opt] for opt in keys}


def leading(counts: Mapping[str, int]) -> str | None:
    """Find the option with the most votes.

    Returns:
        The leading option. None when no vote exists or when the top is a tie.
    """
    top = max(counts.values(), default=0)
    winners = tuple(opt for opt, n in counts.items() if n == top)
    return winners[0] if top > 0 and len(winners) == 1 else None


def _quorum_met(quorum: Quorum | None, participation: int, eligible: int) -> bool:
    """Check the quorum against the turnout.

    A quorum of None is always met. A percent quorum fails when no voter is eligible
    (fail-closed).

    The percent check ``participation / eligible * 100 >= value`` runs as
    ``participation * 100 >= value * eligible``, so it needs no division.
    """
    if quorum is None:
        return True
    value = Decimal(str(quorum.value))
    return (
        Decimal(participation) >= value
        if quorum.type == "count"
        else eligible > 0 and Decimal(participation) * Decimal(100) >= value * Decimal(eligible)
    )


def _quorum_reached(
    quorum: Quorum | None,
    basis: QuorumBasis,
    min_present: int | None,
    *,
    ballots: int,
    eligible: int,
    present: int | None,
) -> bool:
    """Check the quorum of a vote against the ballots or the present persons.

    ``present`` is the number of present roster persons of a meeting vote, or None for
    a vote without a meeting. A vote with the basis ``present`` and a present count
    compares that count; each other vote compares ``ballots``. The least number of
    present persons applies only with a present count.
    """
    by_present = basis == "present" and present is not None
    enough = present is None or min_present is None or present >= min_present
    turnout = present if by_present and present is not None else ballots
    return enough and _quorum_met(quorum, turnout, eligible)


def _by_sign(margin: int) -> VoteResult:
    """Give passed for a positive margin, rejected for a negative one and tie for zero."""
    return "passed" if margin > 0 else ("rejected" if margin < 0 else "tie")


def _two_thirds(yes: int, no: int) -> VoteResult:
    """Apply the 2/3 rule to the decisive votes (yes plus no).

    A side passes or rejects at a share of 2/3 or more. When neither side reaches 2/3, a
    blocking minority holds and the result is a tie. No decisive vote is a tie too.
    """
    decisive = yes + no
    passes = decisive > 0 and 3 * yes >= 2 * decisive
    rejects = decisive > 0 and 3 * no >= 2 * decisive
    return "passed" if passes else ("rejected" if rejects else "tie")


def _majority(rule: MajorityRule, yes: int, no: int, cast: int, eligible: int) -> VoteResult:
    """Apply the majority rule to the yes and no counts.

    The `two_thirds` rule accepts at a share of 2/3 or more, and rejects symmetrically.
    When neither side reaches 2/3, a blocking minority holds and the result is a tie.
    A members rule counts the yes ballots against ``eligible`` and has no tie.

    Returns:
        passed, rejected or tie. A tie here is raw and still needs `tieBreak`.
    """
    match rule:
        case "simple":
            return _by_sign(yes - no)
        case "absolute":
            return _by_sign(2 * yes - cast)
        case "two_thirds":
            return _two_thirds(yes, no)
        case "members_majority":
            return "passed" if eligible > 0 and 2 * yes > eligible else "rejected"
        case "members_two_thirds":
            return "passed" if eligible > 0 and 3 * yes >= 2 * eligible else "rejected"
        case _:
            assert_never(rule)


def result(
    config: VoteConfig,
    counts: Mapping[str, int],
    eligible: int,
    *,
    present: int | None = None,
) -> Outcome:
    """Apply the quorum and the majority rule to get the outcome.

    The quorum turnout counts every cast vote. Abstentions drop out only when
    ``abstainCountsQuorum`` is false. A meeting vote passes ``present``, the present
    persons of its roster: with ``quorumBasis = present`` the quorum counts them.
    """
    yes = counts.get(YES, 0)
    no = counts.get(NO, 0)
    abstain = counts.get(ABSTAIN, 0)
    cast = sum(counts.values())

    participation = cast if config.abstain_counts_quorum else cast - abstain
    quorum_met = _quorum_reached(
        config.quorum,
        config.quorum_basis,
        config.quorum_min_present,
        ballots=participation,
        eligible=eligible,
        present=present,
    )
    lead = leading(counts)

    raw = (
        _majority(config.majority_rule, yes, no, cast, eligible) if quorum_met else "rejected"
    )
    final: VoteResult = config.tie_break if raw == "tie" else raw
    return Outcome(result=final, quorum_met=quorum_met, leading=lead)


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
    #: Votes per candidate id. The single-candidate ballot counts ``yes``/``no`` here.
    counts: dict[str, int]
    #: Abstention votes (free seats on the ballots, or ``abstain``).
    abstentions: int
    #: Cast ballots (turnout).
    ballots: int
    elected: tuple[str, ...] = ()
    #: The tie at the seat boundary: the tied candidates and the open seats. With
    #: ``result == 'runoff'`` a runoff decides, with ``result == 'tie'`` the lot.
    tied: tuple[str, ...] = ()
    open_seats: int = 0
    yes: int | None = None
    no: int | None = None

    def display_counts(self) -> dict[str, int]:
        """Return the counts for the tally card: per candidate (or Ja/Nein) and abstain."""
        return {**self.counts, "abstain": self.abstentions}


def _election_quorum(
    config: ElectionConfig, participation: int, eligible: int, present: int | None
) -> bool:
    """Check the quorum of an election: the rule of a motion."""
    return _quorum_reached(
        config.quorum,
        config.quorum_basis,
        config.quorum_min_present,
        ballots=participation,
        eligible=eligible,
        present=present,
    )


def _yes_no_outcome(
    config: ElectionConfig, choices: Sequence[str | None], eligible: int, present: int | None
) -> ElectionOutcome:
    counts = tally(("yes", "no", "abstain"), choices)
    ballots = sum(counts.values())
    participation = ballots if config.abstain_counts_quorum else ballots - counts["abstain"]
    quorum_met = _election_quorum(config, participation, eligible, present)
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
    present: int | None = None,
) -> ElectionOutcome:
    """Count an election and find the elected candidates.

    Every stored ballot counts as one ballot. A candidate id that the election does
    not know, a repeated id and a vote beyond the seats do not count (the cast path
    refuses them anyway). Ranking by votes; a candidate needs at least one vote to be
    elected. When more candidates have votes than there are seats, the first
    ``seats`` win, unless a tie crosses the seat boundary: then the candidates above
    the boundary are elected and the lot decides among the tied ones, also with
    several seats (no runoff). A missed quorum elects nobody. ``present`` is the present
    count of a meeting election (see ``result``).

    The sort is stable, so candidates with equal votes keep the order of the candidate
    list.
    """
    raw = tuple(choices)
    if config.yes_no:
        return _yes_no_outcome(config, raw, eligible, present)
    known = config.candidate_ids
    known_ids = frozenset(known)
    picks = tuple(_list_picks(item, known_ids, config.seats) for item in raw)
    hits = Counter(cid for ballot in picks for cid in ballot)
    counts = {cid: hits[cid] for cid in known}
    ballots = len(raw)
    full_abstentions = sum(1 for ballot in picks if not ballot)
    participation = ballots if config.abstain_counts_quorum else ballots - full_abstentions
    quorum_met = _election_quorum(config, participation, eligible, present)
    missed = ElectionOutcome(
        result="rejected",
        quorum_met=False,
        counts=counts,
        abstentions=sum(config.seats - len(ballot) for ballot in picks),
        ballots=ballots,
    )
    ranked = tuple(sorted((cid for cid in known if counts[cid] > 0), key=lambda c: -counts[c]))
    return _seat_outcome(missed, ranked, config.seats) if quorum_met else missed


def _list_picks(raw: str | None, known: Collection[str], limit: int) -> tuple[str, ...]:
    """Return the known ids of one list ballot, without repeats and cut at ``limit``."""
    distinct = dict.fromkeys(decode_election_choice(raw) or [])
    return tuple(c for c in distinct if c in known)[:limit]


def _seat_outcome(base: ElectionOutcome, ranked: tuple[str, ...], seats: int) -> ElectionOutcome:
    """Fill the seats of a quorate election from the candidates ranked by votes.

    The first ``seats`` candidates win, unless a tie crosses the seat boundary: then the
    candidates above the boundary are elected and the lot decides among the tied ones.
    """
    counts = base.counts
    fits = len(ranked) <= seats
    boundary = 0 if fits else counts[ranked[seats - 1]]
    clear_cut = fits or counts[ranked[seats]] < boundary
    above = tuple(c for c in ranked if counts[c] > boundary)
    tied = tuple(c for c in ranked if counts[c] == boundary)
    return (
        replace(
            base,
            result="elected" if ranked else "rejected",
            quorum_met=True,
            elected=ranked[:seats],
        )
        if clear_cut
        else replace(
            base,
            result="tie",
            quorum_met=True,
            elected=above,
            tied=tied,
            open_seats=seats - len(above),
        )
    )


def draw_lot(
    among: Sequence[str], seats: int, choose: Callable[[Sequence[str]], str]
) -> list[str]:
    """Draw ``seats`` distinct candidates from ``among`` with ``choose``.

    The caller passes ``secrets.choice``; a test passes a fixed chooser. The draw
    takes one candidate at a time without replacement.
    """
    pool = list(among)
    return [] if seats <= 0 or not pool else _draw_one_more(pool, seats, choose)


def _draw_one_more(
    pool: list[str], seats: int, choose: Callable[[Sequence[str]], str]
) -> list[str]:
    """Draw one candidate from a non-empty pool, then the rest from the pool without it."""
    pick = choose(pool)
    index = pool.index(pick)
    return [pick, *draw_lot([*pool[:index], *pool[index + 1 :]], seats - 1, choose)]


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

    #: Votes per option id. A date poll counts the Ja answers here.
    counts: dict[str, int]
    #: A date poll: the Vielleicht answers per option id. None for the other modes.
    maybe: dict[str, int] | None
    #: Ballots without an option (single and multi only).
    abstentions: int
    #: Cast ballots (turnout).
    ballots: int
    #: The option ids, highest first. Equal options keep the order of the creator.
    order: tuple[str, ...]
    #: The options with the most votes ("meiste Stimmen", "bester Termin"): every tied
    #: option, none while no option has a vote.
    top: tuple[str, ...]

    def display_counts(self) -> dict[str, int]:
        """Return the counts for the tally card: per option, plus ``abstain`` (no date)."""
        return (
            dict(self.counts)
            if self.maybe is not None
            else {**self.counts, ABSTAIN: self.abstentions}
        )


def tally_poll(choices: Iterable[str | None], config: PollConfig) -> PollOutcome:
    """Count a poll.

    Every stored ballot counts as one ballot. An unknown option id, a repeated id, a
    pick beyond the limit and an unknown answer do not count (the cast path refuses
    them anyway). A single or multi poll ranks by votes; a date poll ranks by the Ja
    answers, then by Ja plus Vielleicht.
    """
    raw = tuple(choices)
    known = config.option_ids
    return (
        _date_poll(raw, known)
        if config.mode == "date"
        else _list_poll(raw, known, config.choice_limit)
    )


def _date_poll(raw: tuple[str | None, ...], known: Sequence[str]) -> PollOutcome:
    """Count a date poll: the Ja and the Vielleicht answers per option id."""
    known_ids = frozenset(known)
    answers = tuple(
        (oid, answer)
        for item in raw
        for oid, answer in (decode_poll_answers(item) or {}).items()
        if oid in known_ids
    )
    yes_hits = Counter(oid for oid, answer in answers if answer == YES)
    maybe_hits = Counter(oid for oid, answer in answers if answer == "maybe")
    counts = {oid: yes_hits[oid] for oid in known}
    maybe = {oid: maybe_hits[oid] for oid in known}

    def key(oid: str) -> tuple[int, int]:
        return (counts[oid], counts[oid] + maybe[oid])

    order = tuple(sorted(known, key=lambda oid: (-key(oid)[0], -key(oid)[1])))
    best = key(order[0])
    top = tuple(oid for oid in order if key(oid) == best) if best[1] > 0 else ()
    return PollOutcome(counts, maybe, 0, len(raw), order, top)


def _list_poll(raw: tuple[str | None, ...], known: Sequence[str], limit: int) -> PollOutcome:
    """Count a single or multi poll: the picks per option id and the empty ballots."""
    known_ids = frozenset(known)
    picks = tuple(_list_picks(item, known_ids, limit) for item in raw)
    hits = Counter(oid for ballot in picks for oid in ballot)
    counts = {oid: hits[oid] for oid in known}
    abstentions = sum(1 for ballot in picks if not ballot)
    order = tuple(sorted(known, key=lambda oid: -counts[oid]))
    most = counts[order[0]]
    top = tuple(oid for oid in order if counts[oid] == most) if most > 0 else ()
    return PollOutcome(counts, None, abstentions, len(raw), order, top)
