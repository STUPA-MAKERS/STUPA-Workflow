"""The Wahlgänge of an election by the majority of the members (§F/meetings/voting/000971).

The pure tally per Wahlgang and the candidates of the third Wahlgang, without a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.modules.voting.tally import (
    encode_election_choice,
    needs_members_majority,
    tally_election,
    third_round_field,
)
from app.shared.config_schemas import ElectionConfig


def _config(n: int = 3, **over: Any) -> ElectionConfig:
    data: dict[str, Any] = {
        "seats": 1,
        "candidates": [{"id": f"c{i}", "name": f"Person {i}"} for i in range(1, n + 1)],
        "majorityRule": "members_majority",
    }
    data.update(over)
    return ElectionConfig.model_validate(data)


def _ballots(*picks: Sequence[str]) -> list[str]:
    return [encode_election_choice(p) for p in picks]


@pytest.mark.parametrize("round_", [1, 2])
def test_first_and_second_round_need_the_members_majority(round_: int) -> None:
    out = tally_election(_ballots(["c1"], ["c1"], ["c2"]), _config(), 5, round_=round_)
    assert out.result == "no_majority"
    assert out.elected == ()


def test_third_round_takes_the_simple_majority() -> None:
    out = tally_election(_ballots(["c1"], ["c1"], ["c2"]), _config(n=2), 9, round_=3)
    assert out.result == "elected"
    assert out.elected == ("c1",)


def test_third_round_tie_goes_to_the_lot() -> None:
    out = tally_election(_ballots(["c1"], ["c2"]), _config(n=2), 9, round_=3)
    assert out.result == "tie"
    assert out.tied == ("c1", "c2")
    assert out.open_seats == 1


def test_third_round_with_one_candidate_takes_more_yes_than_no() -> None:
    config = _config(n=1)
    assert tally_election(["yes", "yes", "no"], config, 9, round_=3).result == "elected"
    assert tally_election(["yes", "no"], config, 9, round_=3).result == "rejected"
    assert tally_election(["yes", "yes", "no"], config, 9, round_=2).result == "no_majority"


def test_third_round_with_a_missed_quorum_is_rejected() -> None:
    config = _config(n=2, quorum={"type": "count", "value": 4})
    out = tally_election(_ballots(["c1"], ["c1"]), config, 9, round_=3)
    assert out.result == "rejected"
    assert out.quorum_met is False


def test_only_a_members_election_changes_with_the_round() -> None:
    relative = ElectionConfig.model_validate(
        {"seats": 1, "candidates": [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"}]}
    )
    assert needs_members_majority(relative, 1) is False
    assert needs_members_majority(_config(), 2) is True
    assert needs_members_majority(_config(), 3) is False


def test_two_strongest_stand_in_the_third_round() -> None:
    field = third_round_field(["c1", "c2", "c3"], {"c1": 1, "c2": 4, "c3": 3})
    assert field.sure == ("c2", "c3")
    assert field.open_places == 0


def test_two_candidates_or_fewer_all_stand() -> None:
    assert third_round_field(["c1", "c2"], {"c1": 0, "c2": 5}).sure == ("c2", "c1")
    assert third_round_field(["c1"], {}).sure == ("c1",)


def test_a_tie_for_the_second_place_leaves_one_place_to_the_lot() -> None:
    field = third_round_field(["c1", "c2", "c3"], {"c1": 4, "c2": 2, "c3": 2})
    assert field.sure == ("c1",)
    assert field.tied == ("c2", "c3")
    assert field.open_places == 1


def test_a_tie_of_three_at_the_top_leaves_both_places_to_the_lot() -> None:
    field = third_round_field(["c1", "c2", "c3"], {"c1": 2, "c2": 2, "c3": 2})
    assert field.sure == ()
    assert field.tied == ("c1", "c2", "c3")
    assert field.open_places == 2


def _snippet(round_: int, **over: Any) -> str:
    from app.modules.protocol.markdown import (
        ElectionLine,
        ElectionSnippet,
        build_election_snippet,
    )

    public = bool(over.pop("public", False))
    view = ElectionSnippet(
        question="Vorsitz",
        seats=1,
        round=round_,
        candidates=[ElectionLine(name="Ada", votes=3), ElectionLine(name="Ben", votes=2)],
        abstentions=0,
        members_majority=True,
        **over,
    )
    return build_election_snippet(view, public=public)


def test_protocol_names_the_round_and_its_majority() -> None:
    second = _snippet(2)
    assert "**Vorsitz (2. Wahlgang)**" in second
    assert "Mehrheit der Mitglieder" in second
    assert "Stichwahl" not in second
    assert "> Keine Mehrheit der Mitglieder." in second
    third = _snippet(3)
    assert "einfache Mehrheit" in third
    assert "Keine Mehrheit der Mitglieder" not in third


def test_protocol_names_the_lot_for_a_place_in_the_third_round() -> None:
    assert "das Los bestimmt für den 3. Wahlgang: Ben" in _snippet(2, next_round_lot_names=["Ben"])
    public = _snippet(2, next_round_lot_names=["Ben"], public=True)
    assert "das Los bestimmt einen Platz im 3. Wahlgang." in public
    assert "Ben" not in public.split("Gleichstand")[1]


def test_public_result_drops_the_sub_of_the_lot_for_a_place() -> None:
    from app.modules.voting.schemas import ElectionLotOut, ElectionResultOut

    lot = ElectionLotOut(among=["c2", "c3"], drawn=["c3"], by="lead", byName="Mara Keller")
    result = ElectionResultOut(counts={}, nextRoundLot=lot)
    public = result.public()
    assert public.next_round_lot is not None
    assert public.next_round_lot.by is None
    assert public.next_round_lot.by_name == "Mara Keller"
    plain = ElectionResultOut(counts={})
    assert plain.public() is plain
