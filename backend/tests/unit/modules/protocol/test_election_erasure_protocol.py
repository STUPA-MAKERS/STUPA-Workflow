"""F2 · Erasure of a candidate name from the copies of an election in the protocol text.

``embed_votes`` writes the internal election callout into ``protocol.markdown``, and the
protokollant can insert it into an agenda item body. After the erasure of a candidate
who was not elected, these copies carry ``Gelöscht`` instead of the name; the elected
names, the votes and every other text stay.
"""

from __future__ import annotations

import copy
from typing import Any
from uuid import uuid4

from app.modules.livevote.models import MeetingAgendaItem
from app.modules.protocol.erasure import erase_candidate_names, rewrite_callouts
from app.modules.protocol.models import Protocol
from app.modules.voting.erasure import ERASED_CANDIDATE_NAME, ErasedCandidacy
from app.modules.voting.models import Vote
from tests._support.privacy_fakes import FakeResult, FakeSession

MEETING = uuid4()

_OLD = {
    "seats": 1,
    "candidates": [
        {"id": "c1", "name": "Anna", "principalId": str(uuid4())},
        {"id": "c2", "name": "Ben"},
    ],
}
_NEW = copy.deepcopy(_OLD)
_NEW["candidates"][0]["name"] = ERASED_CANDIDATE_NAME

_RESULT = {
    "counts": {"c1": 2, "c2": 5},
    "abstentions": 1,
    "elected": ["c2"],
}

OLD_CALLOUT = "\n".join(
    [
        "> [!abstimmung] **Wahl Kasse**",
        "> Wahl · 1 Posten",
        "> Ben: 5 · Anna: 2 · Enthaltungen: 1",
        "> Gewählt: Ben",
    ]
)
NEW_VOTES_LINE = f"> Ben: 5 · {ERASED_CANDIDATE_NAME}: 2 · Enthaltungen: 1"


def _vote(
    *, result: dict[str, Any] | None = _RESULT, meeting: Any = MEETING, round_: int | None = 1
) -> Vote:
    return Vote(
        id=uuid4(),
        kind="election",
        status="closed" if result else "open",
        config=_NEW,
        election_result=result,
        meeting_id=meeting,
        question="Wahl Kasse",
        round=round_,
    )


def _erased(vote: Vote) -> ErasedCandidacy:
    return ErasedCandidacy(vote=vote, old_config=_OLD)


NEW_CALLOUT = OLD_CALLOUT.replace("> Ben: 5 · Anna: 2 · Enthaltungen: 1", NEW_VOTES_LINE)
_CHANGE = (OLD_CALLOUT.split("\n"), NEW_CALLOUT.split("\n"))


def test_rewrite_changes_only_the_lines_inside_the_matching_callout() -> None:
    text = "\n".join(
        [
            "Intro: Ben: 5 · Anna: 2 · Enthaltungen: 1",
            "",
            "  " + OLD_CALLOUT.replace("\n", "\n  "),
            "",
            "> Ben: 5 · Anna: 2 · Enthaltungen: 1",
        ]
    )
    out = rewrite_callouts(text, [_CHANGE]).split("\n")
    # The plain text before and the quote after the callout stay; the indent stays.
    assert out[0] == "Intro: Ben: 5 · Anna: 2 · Enthaltungen: 1"
    assert out[2] == "  > [!abstimmung] **Wahl Kasse**"
    assert out[4] == "  " + NEW_VOTES_LINE
    assert out[5] == "  > Gewählt: Ben"
    assert out[-1] == "> Ben: 5 · Anna: 2 · Enthaltungen: 1"


def test_rewrite_without_the_callout_returns_the_text() -> None:
    text = "no callout here\n> Ben: 5 · Anna: 2 · Enthaltungen: 1\n> [!note] other"
    assert rewrite_callouts(text, [_CHANGE]) == text


def test_edited_or_longer_callout_stays() -> None:
    # A callout that the protokollant edited (or extended) is no copy of the election.
    edited = OLD_CALLOUT.replace("> Gewählt: Ben", "> Gewählt: Ben (nimmt an)")
    longer = OLD_CALLOUT + "\n> Anmerkung"
    shorter = OLD_CALLOUT.rsplit("\n", 1)[0]
    for text in (edited, longer, shorter):
        assert rewrite_callouts(text, [_CHANGE]) == text


# Two elections of one meeting with the same head line ("**Wahlgang**" when the
# question is missing): the person lost the first and won the second.
_LOST = "\n".join(
    [
        "> [!abstimmung] **Wahlgang**",
        "> Wahl · 1 Posten",
        "> Kandidatur: Max Muster",
        "> ja: 1, nein: 4, enthaltung: 0",
        "> Gewählt: niemand",
    ]
)
_WON = "\n".join(
    [
        "> [!abstimmung] **Wahlgang**",
        "> Wahl · 1 Posten",
        "> Kandidatur: Max Muster",
        "> ja: 4, nein: 1, enthaltung: 0",
        "> Gewählt: Max Muster",
    ]
)
_LOST_CHANGE = (
    _LOST.split("\n"),
    _LOST.replace("Max Muster", ERASED_CANDIDATE_NAME).split("\n"),
)


def test_two_elections_with_the_same_head_change_only_the_lost_one() -> None:
    text = f"{_WON}\n\nText\n\n{_LOST}\n"
    out = rewrite_callouts(text, [_LOST_CHANGE])
    assert out == f"{_WON}\n\nText\n\n" + _LOST.replace("Max Muster", ERASED_CANDIDATE_NAME) + "\n"


def test_adjacent_callouts_are_separate_blocks() -> None:
    # No blank line between the callouts: the next marker line ends the first block.
    for text, expected in (
        (f"{_LOST}\n{_WON}", _LOST_CHANGE[1] + _WON.split("\n")),
        (f"{_WON}\n{_LOST}", _WON.split("\n") + _LOST_CHANGE[1]),
    ):
        assert rewrite_callouts(text, [_LOST_CHANGE]).split("\n") == expected


def test_first_matching_change_wins_and_other_changes_are_tried() -> None:
    text = f"{_LOST}\n\n{OLD_CALLOUT}"
    out = rewrite_callouts(text, [_CHANGE, _LOST_CHANGE])
    assert out == "\n".join(_LOST_CHANGE[1]) + "\n\n" + NEW_CALLOUT


async def test_protocol_and_agenda_copies_get_the_placeholder() -> None:
    protocol = Protocol(meeting_id=MEETING, markdown=f"# TOP\n\n{OLD_CALLOUT}\n")
    untouched = Protocol(meeting_id=MEETING, markdown="Nothing to see.")
    item = MeetingAgendaItem(meeting_id=MEETING, body=f"Text\n\n{OLD_CALLOUT}")
    other_item = MeetingAgendaItem(meeting_id=MEETING, body="No election here.")
    db: Any = FakeSession(
        scalars=[FakeResult([protocol, untouched]), FakeResult([item, other_item])]
    )
    await erase_candidate_names(db, [_erased(_vote())])
    expected = NEW_CALLOUT
    assert protocol.markdown == f"# TOP\n\n{expected}\n"
    assert item.body == f"Text\n\n{expected}"
    assert "Anna" not in protocol.markdown
    assert "> Gewählt: Ben" in protocol.markdown
    assert untouched.markdown == "Nothing to see."
    assert other_item.body == "No election here."
    assert db.committed == 0


async def test_single_candidate_line_gets_the_placeholder() -> None:
    old = {"seats": 1, "candidates": [{"id": "c1", "name": "Anna", "principalId": str(uuid4())}]}
    new = {"seats": 1, "candidates": [{"id": "c1", "name": ERASED_CANDIDATE_NAME}]}
    vote = _vote(
        result={"counts": {}, "yes": 1, "no": 4, "abstentions": 0, "elected": []},
        round_=None,
    )
    vote.config = new
    callout = "\n".join(
        [
            "> [!abstimmung] **Wahl Kasse**",
            "> Wahl · 1 Posten",
            "> Kandidatur: Anna",
            "> ja: 1, nein: 4, enthaltung: 0",
            "> Gewählt: niemand",
        ]
    )
    protocol = Protocol(meeting_id=MEETING, markdown=callout)
    db: Any = FakeSession(scalars=[FakeResult([protocol]), FakeResult([])])
    await erase_candidate_names(db, [ErasedCandidacy(vote=vote, old_config=old)])
    assert f"> Kandidatur: {ERASED_CANDIDATE_NAME}" in protocol.markdown
    assert "Anna" not in protocol.markdown


async def test_open_election_and_election_without_meeting_query_nothing() -> None:
    # An open election writes no names into its callout; a vote without a meeting
    # has no protocol. Neither reads a protocol.
    db: Any = FakeSession()
    calls: list[Any] = []

    async def scalars(stmt: Any) -> FakeResult:
        calls.append(stmt)
        return FakeResult()

    db.scalars = scalars
    await erase_candidate_names(db, [_erased(_vote(result=None)), _erased(_vote(meeting=None))])
    await erase_candidate_names(db, [])
    assert calls == []


async def test_runoff_line_of_the_parent_gets_the_placeholder() -> None:
    vote = _vote(
        result={
            "counts": {"c1": 3, "c2": 3},
            "abstentions": 0,
            "elected": [],
            "runoff": {"candidateIds": ["c1", "c2"], "seats": 1},
        }
    )
    callout = "\n".join(
        [
            "> [!abstimmung] **Wahl Kasse**",
            "> Wahl · 1 Posten",
            "> Anna: 3 · Ben: 3 · Enthaltungen: 0",
            "> Gewählt: niemand",
            "> Stichwahl (2. Wahlgang) um 1 Posten: Anna, Ben",
        ]
    )
    item = MeetingAgendaItem(meeting_id=MEETING, body=callout)
    db: Any = FakeSession(scalars=[FakeResult([]), FakeResult([item])])
    await erase_candidate_names(db, [_erased(vote)])
    assert item.body is not None
    assert "Anna" not in item.body
    assert f"um 1 Posten: {ERASED_CANDIDATE_NAME}, Ben" in item.body
