"""F2 · Personnel elections in the protocol and on the public protocols page.

The internal snippet names every candidate with the votes; the public snippet and the
public decision name the elected candidates only and count the others.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.protocol import service as protocol_service_mod
from app.modules.protocol.markdown import (
    ElectionLine,
    ElectionSnippet,
    build_election_snippet,
    replace_vote_block,
)
from app.modules.protocol.public import PublicDecision, PublicTop
from app.modules.protocol.service import _election_snippet, _snippet
from app.modules.voting.schemas import (
    ElectionLotOut,
    ElectionResultOut,
    ElectionRunoffOut,
    TallyOut,
    VoteOut,
)
from app.shared.config_schemas import ElectionConfig
from tests._support.protocol_fakes import FakeSession, result
from tests.unit.modules.protocol.test_public_service_unit import MID, _service, _Voting

_CONFIG = ElectionConfig.model_validate(
    {
        "seats": 2,
        "candidates": [
            {"id": "c1", "name": "Anna"},
            {"id": "c2", "name": "Ben"},
            {"id": "c3", "name": "Cem"},
        ],
    }
)


def _view(result_out: ElectionResultOut | None, **over: Any) -> VoteOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "eligibleGroup": "g",
        "question": "Wahl der Referate",
        "config": _CONFIG.as_vote_config(),
        "status": "closed" if result_out is not None else "open",
        "result": "elected" if result_out is not None else None,
        "secret": True,
        "tally": TallyOut(counts={}, eligible=9, quorumMet=True),
        "kind": "election",
        "election": _CONFIG,
        "electionResult": result_out,
    }
    base.update(over)
    return VoteOut.model_validate(base)


_RESULT = ElectionResultOut(
    counts={"c1": 3, "c2": 5, "c3": 1}, abstentions=2, ballots=6, elected=["c2", "c1"]
)


def test_internal_snippet_names_every_candidate() -> None:
    text = _snippet(_view(_RESULT), "Beschlussfrage")
    assert text.splitlines()[0] == "> [!abstimmung] **Wahl der Referate**"
    assert "> Wahl · 2 Posten" in text
    # Sorted by votes.
    assert "> Ben: 5 · Anna: 3 · Cem: 1 · Enthaltungen: 2" in text
    assert "> Gewählt: Ben, Anna" in text
    assert "weitere" not in text


def test_public_snippet_names_the_elected_only() -> None:
    text = _snippet(_view(_RESULT), "Beschlussfrage", public=True)
    assert "Cem" not in text
    assert ": 5" not in text
    assert "> Gewählt: Ben, Anna" in text
    assert "> 1 weitere Kandidierende" in text


def test_snippet_of_a_lot_and_a_runoff() -> None:
    lot = _RESULT.model_copy(
        update={"lot": ElectionLotOut(among=["c1", "c3"], drawn=["c1"]), "elected": ["c1"]}
    )
    text = _snippet(_view(lot, round=2), "x")
    assert "Stichwahl (2. Wahlgang)" in text
    assert "> Durch Los entschieden." in text
    pending = _RESULT.model_copy(update={"lot": ElectionLotOut(among=["c1", "c3"])})
    assert "> Gleichstand: das Los steht aus." in _snippet(_view(pending), "x")
    runoff = _RESULT.model_copy(
        update={
            "elected": ["c2"],
            "runoff": ElectionRunoffOut(candidateIds=["c1", "c3"], seats=1),
        }
    )
    internal = _snippet(_view(runoff), "x")
    assert "> Stichwahl (2. Wahlgang) um 1 Posten: Anna, Cem" in internal
    public = _snippet(_view(runoff), "x", public=True)
    assert "> Stichwahl (2. Wahlgang) um 1 Posten: 2 Kandidierende" in public


def test_snippet_of_a_single_candidate() -> None:
    single = ElectionConfig.model_validate(
        {"seats": 1, "candidates": [{"id": "c1", "name": "Anna"}]}
    )
    out = ElectionResultOut(counts={"yes": 7, "no": 2}, abstentions=1, yes=7, no=2, elected=["c1"])
    text = _snippet(_view(out, election=single, config=single.as_vote_config()), "x")
    assert "> Kandidatur: Anna" in text
    assert "> ja: 7, nein: 2, enthaltung: 1" in text
    assert "> Gewählt: Anna" in text


def test_snippet_of_an_open_election_has_no_result() -> None:
    text = _snippet(_view(None, question=None), "x")
    assert text.splitlines() == ["> [!abstimmung] **Wahlgang**", "> Wahl · 2 Posten"]
    assert _election_snippet(_view(None)).closed is False


def test_build_snippet_without_candidates_and_nobody_elected() -> None:
    view = ElectionSnippet(question="Q", seats=1, yes=0, no=0, candidates=[])
    text = build_election_snippet(view)
    assert "> Kandidatur: " in text
    assert "> Gewählt: niemand" in text
    lines = [ElectionLine(name="A", votes=1, elected=True)]
    public = build_election_snippet(
        ElectionSnippet(question="Q", seats=1, candidates=lines), public=True
    )
    assert "weitere" not in public


def test_replace_vote_block() -> None:
    body = "Text\n> [!abstimmung] **Q**\n> A: 3 · B: 1\n> Gewählt: A\nMehr"
    new = "> [!abstimmung] **Q**\n> Gewählt: A"
    assert replace_vote_block(body, new) == "Text\n> [!abstimmung] **Q**\n> Gewählt: A\nMehr"
    assert replace_vote_block("Nichts", new) == "Nichts"


def test_public_decision_of_an_election() -> None:
    lot = _RESULT.model_copy(update={"lot": ElectionLotOut(among=["c1"], drawn=["c1"])})
    decision = PublicDecision.from_vote(_view(lot, round=2))
    assert decision.kind == "election"
    assert decision.elected == ["Ben", "Anna"]
    assert decision.other_candidates == 1
    assert decision.counts == {}
    assert decision.by_lot is True
    assert decision.round == 2
    assert decision.seats == 2
    empty = PublicDecision.from_vote(_view(None))
    assert empty.elected == [] and empty.other_candidates == 3


async def test_public_assembly_replaces_the_election_in_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _view(_RESULT)
    internal = _snippet(view, "x")
    item = SimpleNamespace(
        id=uuid4(), title="Wahlen", body=f"Vorstellung\n\n{internal}", non_public=False
    )
    vote = SimpleNamespace(id=uuid4())
    _Voting.views = {vote.id: view}
    monkeypatch.setattr(protocol_service_mod, "VotingService", _Voting)
    session = FakeSession(results=[result(item), result(vote)])
    tops: list[PublicTop] = []
    md = await _service(session)._assemble_from_agenda(MID, public=True, tops=tops)
    assert "Cem" not in md
    assert md.count("Gewählt: Ben, Anna") == 1
    assert tops[0].decisions[0].in_text is True
    assert tops[0].decisions[0].elected == ["Ben", "Anna"]
    session = FakeSession(results=[result(item), result(vote)])
    md = await _service(session)._assemble_from_agenda(MID)
    assert "Cem: 1" in md
