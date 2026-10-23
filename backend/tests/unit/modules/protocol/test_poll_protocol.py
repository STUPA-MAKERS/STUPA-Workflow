"""Polls in the protocol: the snippet (question, options, counts) and the public page.

A poll lists counts only, never a name, and it is no decision: the public decisions
leave it out.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from app.modules.protocol import service as protocol_service_mod
from app.modules.protocol.markdown import PollLine, PollSnippet, build_poll_snippet
from app.modules.protocol.public import PublicTop
from app.modules.protocol.service import (
    _snippet,
    poll_meta,
    poll_option_label,
    poll_snippet_of,
)
from app.modules.voting.schemas import PollResultOut, TallyOut, VoteOut
from app.shared.config_schemas import PollConfig
from tests._support.protocol_fakes import FakeSession, result
from tests.unit.modules.protocol.test_public_service_unit import MID, _service, _Voting

BERLIN = ZoneInfo("Europe/Berlin")
_SINGLE = PollConfig.model_validate(
    {
        "mode": "single",
        "options": [
            {"id": "o1", "label": "Ja"},
            {"id": "o2", "label": "Nein"},
            {"id": "o3", "label": "Café *Mitte*"},
        ],
    }
)
_DATE = PollConfig.model_validate(
    {
        "mode": "date",
        "options": [
            {"id": "o1", "start": "2026-11-03T18:00:00+01:00", "end": "2026-11-03T20:00:00+01:00"},
            {"id": "o2", "start": "2026-11-04T17:00:00Z"},
        ],
    }
)


def _view(config: PollConfig, res: PollResultOut | None, **over: Any) -> VoteOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "eligibleGroup": "g",
        "question": "Wohin?",
        "config": config.as_vote_config(),
        "status": "closed" if res is not None else "open",
        "secret": False,
        "tally": TallyOut(counts={}, eligible=9, quorumMet=True),
        "kind": "poll",
        "poll": config,
        "pollResult": res,
    }
    base.update(over)
    return VoteOut.model_validate(base)


_RESULT = PollResultOut(
    counts={"o1": 4, "o2": 1, "o3": 4},
    abstentions=1,
    ballots=10,
    order=["o1", "o3", "o2"],
    top=["o1", "o3"],
)


def test_snippet_of_a_closed_single_poll() -> None:
    text = _snippet(_view(_SINGLE, _RESULT), "Beschlussfrage", tz=BERLIN)
    assert text.splitlines() == [
        "> [!abstimmung] **Wohin?**",
        "> Umfrage · Einzelwahl",
        "> Ja: 4",
        "> Café *Mitte*: 4",
        "> Nein: 1",
        "> Enthaltungen: 1",
        "> Meiste Stimmen: Ja, Café *Mitte*",
        "> 10 Antworten",
    ]
    # The public variant is the same: a poll never lists names.
    assert _snippet(_view(_SINGLE, _RESULT), "x", public=True) == text


def test_snippet_of_a_closed_date_poll() -> None:
    res = PollResultOut(
        counts={"o1": 3, "o2": 3},
        maybe={"o1": 2},
        ballots=5,
        order=["o1", "o2"],
        top=["o1"],
    )
    text = _snippet(_view(_DATE, res, question=None), "x")
    assert text.splitlines() == [
        "> [!abstimmung] **Umfrage**",
        "> Terminumfrage",
        "> Di, 3.11. · 18:00–20:00: 3 (+2)",
        "> Mi, 4.11. · 18:00: 3 (+0)",
        "> Zahl = Ja, (+n) = Vielleicht",
        "> Bester Termin: Di, 3.11. · 18:00–20:00",
        "> 5 Antworten",
    ]


def test_snippet_of_an_open_poll_has_no_counts() -> None:
    text = _snippet(_view(_SINGLE, None), "x")
    assert text.splitlines() == ["> [!abstimmung] **Wohin?**", "> Umfrage · Einzelwahl"]
    view = poll_snippet_of(_DATE, None, question=" ", tz=BERLIN)
    assert view.closed is False
    assert view.question == "Umfrage"
    assert view.abstentions is None
    assert view.ballots == 0


def test_snippet_without_votes_names_no_top_and_keeps_the_option_order() -> None:
    empty = PollResultOut(counts={}, ballots=0)
    view = poll_snippet_of(_SINGLE, empty, question="Q", tz=BERLIN)
    assert [line.label for line in view.lines] == ["Ja", "Nein", "Café *Mitte*"]
    assert [line.count for line in view.lines] == [0, 0, 0]
    text = build_poll_snippet(view)
    assert "Meiste Stimmen" not in text
    assert "> 0 Antworten" in text


def test_poll_meta_of_every_mode() -> None:
    assert poll_meta(_SINGLE) == "Umfrage · Einzelwahl"
    assert poll_meta(_DATE) == "Terminumfrage"
    multi = PollConfig.model_validate({"mode": "multi", "options": _SINGLE.model_dump()["options"]})
    assert poll_meta(multi) == "Umfrage · Mehrfachwahl"
    capped = multi.model_copy(update={"max_choices": 2})
    assert poll_meta(capped) == "Umfrage · Mehrfachwahl, höchstens 2"


def test_option_label() -> None:
    assert poll_option_label(_SINGLE.options[0], BERLIN) == "Ja"
    assert poll_option_label(_DATE.options[1], BERLIN) == "Mi, 4.11. · 18:00"


def test_build_snippet_of_a_bare_view() -> None:
    view = PollSnippet(question="Q", meta="Umfrage · Einzelwahl", lines=[PollLine("A", 1)])
    assert build_poll_snippet(view).endswith("> 0 Antworten")


async def test_public_assembly_lists_no_poll_as_a_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _view(_SINGLE, _RESULT)
    item = SimpleNamespace(id=uuid4(), title="Stimmungsbild", body="Text", non_public=False)
    vote = SimpleNamespace(id=uuid4())
    _Voting.views = {vote.id: view}
    monkeypatch.setattr(protocol_service_mod, "VotingService", _Voting)
    session = FakeSession(results=[result(item), result(vote)])
    tops: list[PublicTop] = []
    md = await _service(session)._assemble_from_agenda(MID, public=True, tops=tops)
    assert "> Meiste Stimmen: Ja, Café *Mitte*" in md
    assert tops[0].decisions == []
