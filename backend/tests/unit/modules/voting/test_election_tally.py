"""F2 · Personnel elections: the pure election tally, the ballot codec and the lot.

No database and no clock: every branch of `tally_election`, `draw_lot`, the ballot
codec and the `ElectionConfig` rules runs here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.voting.tally import (
    decode_election_choice,
    draw_lot,
    encode_election_choice,
    tally_election,
)
from app.shared.config_schemas import ElectionConfig, VoteConfig


def _config(seats: int = 1, n: int = 3, **over: Any) -> ElectionConfig:
    data: dict[str, Any] = {
        "seats": seats,
        "candidates": [{"id": f"c{i}", "name": f"Person {i}"} for i in range(1, n + 1)],
    }
    data.update(over)
    return ElectionConfig.model_validate(data)


def _ballots(*picks: Sequence[str]) -> list[str]:
    return [encode_election_choice(p) for p in picks]


# ---------------------------------------------------------------- codec


def test_encode_sorts_and_compacts() -> None:
    assert encode_election_choice(["c2", "c1"]) == '["c1","c2"]'
    assert encode_election_choice([]) == "[]"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("not json", None),
        ('{"a": 1}', None),
        ("[1, 2]", None),
        ('["c1","c2"]', ["c1", "c2"]),
        ("[]", []),
    ],
)
def test_decode(raw: str | None, expected: list[str] | None) -> None:
    assert decode_election_choice(raw) == expected


# ---------------------------------------------------------------- config


def test_config_defaults_secret_and_projection() -> None:
    config = _config(seats=2, n=3)
    assert config.secret is True
    assert config.yes_no is False
    projected = config.as_vote_config()
    assert projected.options == ["c1", "c2", "c3", "abstain"]
    assert projected.secret is True
    assert projected.tie_break == "tie"


def test_config_single_candidate_projects_yes_no() -> None:
    config = _config(seats=1, n=1)
    assert config.yes_no is True
    assert config.as_vote_config().options == ["yes", "no", "abstain"]


def test_from_stored_projects_an_election_row() -> None:
    stored = _config(seats=2, n=3, secret=False).model_dump(mode="json", by_alias=True)
    projected = VoteConfig.from_stored(stored)
    assert projected.options == ["c1", "c2", "c3", "abstain"]
    assert projected.secret is False


@pytest.mark.parametrize(
    "over",
    [
        {"candidates": [{"id": "c1", "name": "A"}, {"id": "c1", "name": "B"}]},
        {"candidates": [{"id": "yes", "name": "A"}, {"id": "c2", "name": "B"}]},
        {
            "candidates": [
                {"id": "c1", "name": "A", "principalId": "00000000-0000-0000-0000-000000000001"},
                {"id": "c2", "name": "B", "principalId": "00000000-0000-0000-0000-000000000001"},
            ]
        },
        {"seats": 4},
        {"guestsVote": True, "quorum": {"type": "count", "value": 2}},
        {"candidates": [{"id": "c1", "name": "   "}]},
        {"candidates": []},
    ],
)
def test_config_rejects(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _config(**{"seats": 1, "n": 3, **over})


def test_config_strips_names() -> None:
    config = _config(candidates=[{"id": "c1", "name": "  Anna  "}])
    assert config.candidates[0].name == "Anna"


# ---------------------------------------------------------------- single candidate


def test_yes_no_elected_when_yes_beats_no() -> None:
    out = tally_election(["yes", "yes", "no", "abstain"], _config(n=1), 10)
    assert out.result == "elected"
    assert out.elected == ("c1",)
    assert (out.yes, out.no, out.abstentions, out.ballots) == (2, 1, 1, 4)
    assert out.display_counts() == {"yes": 2, "no": 1, "abstain": 1}


def test_yes_no_rejected_on_a_tie() -> None:
    out = tally_election(["yes", "no"], _config(n=1), 10)
    assert out.result == "rejected"
    assert out.elected == ()


def test_yes_no_quorum_without_abstentions() -> None:
    config = _config(n=1, quorum={"type": "count", "value": 2}, abstainCountsQuorum=False)
    out = tally_election(["yes", "abstain", "abstain"], config, 10)
    assert out.quorum_met is False
    assert out.result == "rejected"
    assert out.elected == ()


# ---------------------------------------------------------------- several candidates


def test_single_seat_clear_winner() -> None:
    out = tally_election(_ballots(["c1"], ["c1"], ["c2"], []), _config(), 10)
    assert out.result == "elected"
    assert out.elected == ("c1",)
    assert out.counts == {"c1": 2, "c2": 1, "c3": 0}
    assert out.abstentions == 1
    assert out.ballots == 4


def test_single_seat_tie_goes_to_the_lot() -> None:
    out = tally_election(_ballots(["c1"], ["c2"]), _config(), 10)
    assert out.result == "tie"
    assert out.elected == ()
    assert out.tied == ("c1", "c2")
    assert out.open_seats == 1


def test_multi_seat_boundary_tie_goes_to_a_runoff() -> None:
    ballots = _ballots(["c1", "c2"], ["c1", "c3"], ["c1", "c4"])
    out = tally_election(ballots, _config(seats=2, n=4), 10)
    assert out.result == "runoff"
    assert out.elected == ("c1",)
    assert out.tied == ("c2", "c3", "c4")
    assert out.open_seats == 1


def test_runoff_round_tie_goes_to_the_lot() -> None:
    ballots = _ballots(["c1", "c2"], ["c3", "c4"])
    out = tally_election(ballots, _config(seats=2, n=4), 10, round_=2)
    assert out.result == "tie"
    assert out.elected == ()
    assert out.open_seats == 2


def test_multi_seat_without_boundary_tie() -> None:
    ballots = _ballots(["c1", "c2"], ["c1", "c2"], ["c1", "c3"])
    out = tally_election(ballots, _config(seats=2, n=3), 10)
    assert out.result == "elected"
    assert out.elected == ("c1", "c2")
    # 3 ballots * 2 seats = 6 votes, all given.
    assert out.abstentions == 0


def test_fewer_candidates_with_votes_than_seats() -> None:
    # A candidate needs at least one vote. The free seat stays empty.
    out = tally_election(_ballots(["c1"], ["c1"]), _config(seats=2, n=3), 10)
    assert out.result == "elected"
    assert out.elected == ("c1",)
    assert out.abstentions == 2


def test_nobody_elected_when_all_abstain() -> None:
    out = tally_election(_ballots([], []), _config(seats=2, n=3), 10)
    assert out.result == "rejected"
    assert out.elected == ()
    assert out.abstentions == 4


def test_invalid_entries_do_not_count() -> None:
    # A repeated id, an unknown id, a vote beyond the seats and a garbled row.
    ballots = ['["c1","c1","x"]', '["c1","c2","c3"]', "garbled", None]
    out = tally_election(ballots, _config(seats=2, n=3), 10)
    assert out.counts == {"c1": 2, "c2": 1, "c3": 0}
    assert out.ballots == 4
    # 1 + 0 + 2 + 2 free seats.
    assert out.abstentions == 5


def test_quorum_missed_elects_nobody() -> None:
    config = _config(quorum={"type": "percent", "value": 50})
    out = tally_election(_ballots(["c1"]), config, 10)
    assert out.quorum_met is False
    assert out.result == "rejected"
    assert out.elected == ()
    assert out.counts["c1"] == 1


def test_quorum_without_full_abstentions() -> None:
    config = _config(quorum={"type": "count", "value": 2}, abstainCountsQuorum=False)
    assert tally_election(_ballots(["c1"], []), config, 10).quorum_met is False
    assert tally_election(_ballots(["c1"], ["c2"]), config, 10).quorum_met is True


# ---------------------------------------------------------------- lot


def test_draw_lot_takes_distinct_candidates() -> None:
    picks: list[Sequence[str]] = []

    def first(pool: Sequence[str]) -> str:
        picks.append(list(pool))
        return pool[-1]

    assert draw_lot(["a", "b", "c"], 2, first) == ["c", "b"]
    assert picks == [["a", "b", "c"], ["a", "b"]]


def test_draw_lot_never_draws_more_than_the_pool() -> None:
    assert draw_lot(["a"], 3, lambda pool: pool[0]) == ["a"]
