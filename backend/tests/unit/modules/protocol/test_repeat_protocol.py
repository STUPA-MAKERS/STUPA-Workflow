"""A repeated vote in the protocol.

The repeat has the question of the vote it repeats, so its head names the attempt
(„Frage (2. Abstimmung)“, „Wahl (2. Wahlgang)“). The repeated vote keeps its result and
gets the line „Wiederholt, siehe 2. Abstimmung.“, also when the protokollant already put
its callout into the text. A prepared repeat marks nothing yet.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.protocol import service as protocol_service_mod
from app.modules.protocol.markdown import mark_vote_blocks
from app.modules.protocol.service import _snippet, repeat_mark
from app.modules.voting.schemas import TallyOut, VoteOut
from app.shared.config_schemas import ElectionConfig, VoteConfig
from tests._support.protocol_fakes import FakeSession, result
from tests.unit.modules.protocol.test_public_service_unit import MID, _service, _Voting

_MOTION = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple", "secret": True}
)


def _motion(**over: Any) -> VoteOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "eligibleGroup": "g",
        "question": "Party?",
        "config": _MOTION,
        "status": "closed",
        "result": "passed",
        "secret": True,
        "tally": TallyOut(counts={"yes": 3, "no": 1, "abstain": 0}, eligible=9, quorumMet=True),
    }
    base.update(over)
    return VoteOut.model_validate(base)


def test_repeat_head_names_the_attempt() -> None:
    assert _snippet(_motion(), "x").splitlines()[0] == "> [!abstimmung] **Party?**"
    head = _snippet(_motion(attempt=2), "x").splitlines()[0]
    assert head == "> [!abstimmung] **Party? (2. Abstimmung)**"


def test_repeat_mark_of_a_motion_and_an_election() -> None:
    assert repeat_mark(_motion(attempt=3)) == "Wiederholt, siehe 3. Abstimmung."
    election = ElectionConfig.model_validate(
        {"seats": 1, "candidates": [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"}]}
    )
    view = _motion(
        attempt=2, kind="election", election=election, config=election.as_vote_config()
    )
    assert repeat_mark(view) == "Wiederholt, siehe 2. Wahlgang."


def test_mark_vote_blocks_adds_the_line_once() -> None:
    snippet = "> [!abstimmung] **Party?**\n> yes: 3, no: 1"
    body = f"Text davor\n\n{snippet}\n> Eigene Zeile\n\nText danach"
    marked = mark_vote_blocks(body, [(snippet, "Wiederholt, siehe 2. Abstimmung.")])
    assert marked == (
        "Text davor\n\n> [!abstimmung] **Party?**\n> yes: 3, no: 1\n> Eigene Zeile\n"
        "> Wiederholt, siehe 2. Abstimmung.\n\nText danach"
    )
    assert mark_vote_blocks(marked, [(snippet, "Wiederholt, siehe 2. Abstimmung.")]) == marked
    assert mark_vote_blocks("kein Block", [(snippet, "x")]) == "kein Block"


async def _assemble(
    monkeypatch: pytest.MonkeyPatch, views: list[VoteOut], body: str
) -> str:
    item = SimpleNamespace(id=uuid4(), title="Party", body=body, non_public=False)
    rows = [
        SimpleNamespace(id=view.id, repeat_of_id=view.repeat_of_id, status=view.status)
        for view in views
    ]
    _Voting.views = {row.id: view for row, view in zip(rows, views, strict=True)}
    monkeypatch.setattr(protocol_service_mod, "VotingService", _Voting)
    session = FakeSession(results=[result(item), result(*rows)])
    return await _service(session)._assemble_from_agenda(MID)


async def test_assembly_marks_the_repeated_vote(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _motion()
    second = _motion(attempt=2, repeatOfId=first.id, result="rejected")
    md = await _assemble(monkeypatch, [first, second], "")
    assert "**Party?**\n> yes: 3, no: 1, abstain: 0\n> Wiederholt, siehe 2. Abstimmung." in md
    assert "**Party? (2. Abstimmung)**" in md
    assert md.count("Wiederholt") == 1


async def test_assembly_marks_the_callout_in_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _motion()
    second = _motion(attempt=2, repeatOfId=first.id)
    md = await _assemble(monkeypatch, [first, second], _snippet(first, "x"))
    assert md.count("**Party?**") == 1
    assert md.count("Wiederholt, siehe 2. Abstimmung.") == 1


async def test_prepared_repeat_marks_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    first = _motion()
    second = _motion(attempt=2, repeatOfId=first.id, status="draft", result=None)
    md = await _assemble(monkeypatch, [first, second], "")
    assert "Wiederholt" not in md




def test_repeat_of_an_election_names_the_next_ballot() -> None:
    election = ElectionConfig.model_validate(
        {"seats": 1, "candidates": [{"id": "c1", "name": "A"}, {"id": "c2", "name": "B"}]}
    )
    view = _motion(
        question="Vorsitz",
        attempt=2,
        kind="election",
        election=election,
        config=election.as_vote_config(),
        status="open",
        result=None,
    )
    head, meta = _snippet(view, "x").splitlines()[:2]
    assert head == "> [!abstimmung] **Vorsitz (2. Wahlgang)**"
    assert meta == "> Wahl · 1 Posten"
