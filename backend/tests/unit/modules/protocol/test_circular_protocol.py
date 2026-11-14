"""The Umlaufverfahren in the protocol, without a database (spec 000916).

Also the protocol lines of an election with the majority of the members (spec 000912).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.modules.protocol.circular import (
    CIRCULAR_LEAD,
    build_circular_block,
    circular_block,
    circular_note,
    circular_snippet,
)
from app.modules.protocol.markdown import ElectionLine, ElectionSnippet, build_election_snippet
from app.modules.protocol.service import election_snippet_of
from app.modules.voting.circular import circular_config
from app.modules.voting.schemas import ElectionResultOut, TallyOut, VoteOut
from app.shared.config_schemas import ElectionConfig
from tests._support.protocol_fakes import FakeSession

TZ = ZoneInfo("Europe/Berlin")
CLOSED = datetime(2026, 11, 9, 23, 30, tzinfo=UTC)


def _view(**over: Any) -> VoteOut:
    data: dict[str, Any] = {
        "id": uuid4(),
        "eligibleGroup": "g",
        "question": "Soll der AStA einen Lastenanhänger beschaffen?",
        "config": circular_config(),
        "status": "closed",
        "result": "passed",
        "secret": True,
        "closedAt": CLOSED,
        "tally": TallyOut(counts={"yes": 5, "no": 1, "abstain": 0}, eligible=8, quorumMet=True),
        "kind": "circular",
    }
    data.update(over)
    return VoteOut.model_validate(data)


def test_note_names_the_local_day_and_the_result() -> None:
    assert circular_note("passed", CLOSED, TZ) == (
        "Umlaufverfahren · beendet am 10.11.2026 · angenommen"
    )
    assert circular_note("rejected", None, TZ) == "Umlaufverfahren · abgelehnt"
    assert circular_note(None, None, TZ) == "Umlaufverfahren · abgelehnt"


def test_snippet_holds_the_question_the_counts_and_the_result() -> None:
    lines = circular_snippet(_view(), TZ).splitlines()
    assert lines == [
        "> [!abstimmung] **Soll der AStA einen Lastenanhänger beschaffen?**",
        "> yes: 5, no: 1, abstain: 0",
        "> Umlaufverfahren · beendet am 10.11.2026 · angenommen",
    ]
    assert "**Umlaufverfahren**" in circular_snippet(_view(question=None), TZ)


def test_block_has_the_lead_only_with_a_vote() -> None:
    assert build_circular_block([]) == ""
    assert build_circular_block(["> a", "> b"]) == f"{CIRCULAR_LEAD}\n\n> a\n\n> b"


class _Voting:
    def __init__(self, views: dict[Any, VoteOut]) -> None:
        self.views = views

    async def get(self, vote_id: Any) -> VoteOut:
        return self.views[vote_id]


async def test_block_without_a_meeting_or_a_gremium_is_empty() -> None:
    voting: Any = _Voting({})
    session: Any = FakeSession()
    assert await circular_block(session, None, voting, TZ) == ""
    meeting: Any = SimpleNamespace(id=uuid4())
    assert await circular_block(session, meeting, voting, TZ) == ""


async def test_block_lists_the_circular_votes_of_the_gremium() -> None:
    view = _view()
    session: Any = FakeSession()
    session.circular_ids = [view.id]
    voting: Any = _Voting({view.id: view})
    for started in (None, datetime(2026, 11, 12, 18, 0, tzinfo=UTC)):
        meeting: Any = SimpleNamespace(id=uuid4(), gremium_id=uuid4(), started_at=started)
        block = await circular_block(session, meeting, voting, TZ)
        assert block.startswith(CIRCULAR_LEAD)
        assert "Lastenanhänger" in block


_MEMBERS = ElectionConfig.model_validate(
    {
        "seats": 1,
        "majorityRule": "members_majority",
        "candidates": [{"id": "c1", "name": "Anna"}, {"id": "c2", "name": "Ben"}],
    }
)


def test_election_with_the_members_rule_names_it() -> None:
    missed = ElectionResultOut(counts={"c1": 3, "c2": 2}, abstentions=0, ballots=5, elected=[])
    text = build_election_snippet(
        election_snippet_of(_MEMBERS, missed, question="Vorsitz", round_=1)
    )
    assert "> Wahl · 1 Posten · Mehrheit der Mitglieder" in text
    assert "> Gewählt: niemand" in text
    assert "> Keine Mehrheit der Mitglieder." in text

    won = ElectionResultOut(counts={"c1": 5, "c2": 0}, abstentions=0, ballots=5, elected=["c1"])
    elected = build_election_snippet(
        election_snippet_of(_MEMBERS, won, question="Vorsitz", round_=1)
    )
    assert "> Gewählt: Anna" in elected
    assert "Keine Mehrheit" not in elected

    plain = build_election_snippet(
        ElectionSnippet(
            question="Q", seats=1, candidates=[ElectionLine(name="A", votes=0)]
        )
    )
    assert "Mehrheit der Mitglieder" not in plain
