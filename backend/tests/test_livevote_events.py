"""WS-Nachrichten-Schema-Test (T-16 DoD, api.md §4).

Stellt den WS-Contract fest, gegen den das FE (T-32/T-33) baut: Feldnamen (camelCase),
Discriminator ``type`` und — sicherheitskritisch — dass Tally-/Closed-Events **nur**
Aggregate tragen (requirements N1a, keine Wähler-Identität).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.livevote.events import (
    CastMessage,
    ErrorEvent,
    MeetingStateEvent,
    SubscribeMessage,
    VoteClosedEvent,
    VoteOpenedEvent,
    VoteTallyEvent,
)


def test_meeting_state_event_camel_and_optional_active() -> None:
    aid = uuid4()
    dumped = MeetingStateEvent(activeApplicationId=aid, status="live").dump()
    assert dumped == {
        "type": "meeting_state",
        "activeApplicationId": str(aid),
        "status": "live",
    }
    # Ohne aktiven Antrag bleibt das Feld null (Beamer zeigt nichts an).
    assert MeetingStateEvent(status="planned").dump()["activeApplicationId"] is None


def test_vote_opened_event_serialises_options_and_iso_closes_at() -> None:
    vid, aid = uuid4(), uuid4()
    closes = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    dumped = VoteOpenedEvent(
        voteId=vid, applicationId=aid, options=["yes", "no", "abstain"], closesAt=closes
    ).dump()
    assert dumped["type"] == "vote_opened"
    assert dumped["voteId"] == str(vid)
    assert dumped["applicationId"] == str(aid)
    assert dumped["options"] == ["yes", "no", "abstain"]
    closes_at = dumped["closesAt"]
    assert isinstance(closes_at, str) and closes_at.startswith("2026-06-06T12:00:00")


def test_vote_tally_event_is_aggregate_only_no_voter_identity() -> None:
    dumped = VoteTallyEvent(
        voteId=uuid4(),
        counts={"yes": 5, "no": 2, "abstain": 1},
        eligible=12,
        quorumMet=True,
        leading="yes",
    ).dump()
    assert dumped["type"] == "vote_tally"
    assert dumped["counts"] == {"yes": 5, "no": 2, "abstain": 1}
    assert dumped["quorumMet"] is True
    assert dumped["leading"] == "yes"
    # Niemals Wähler-Identitäten im Tally (requirements N1a).
    keys = set(dumped)
    assert not (keys & {"voter", "voterSub", "voters", "ballots", "names"})


def test_vote_closed_event_carries_result_and_counts_only() -> None:
    dumped = VoteClosedEvent(
        voteId=uuid4(), result="passed", counts={"yes": 7, "no": 1}
    ).dump()
    assert dumped["type"] == "vote_closed"
    assert dumped["result"] == "passed"
    assert dumped["counts"] == {"yes": 7, "no": 1}
    assert "voter" not in dumped


def test_error_event() -> None:
    assert ErrorEvent(code="not_eligible").dump() == {
        "type": "error",
        "code": "not_eligible",
    }


def test_cast_message_parses_camel_alias() -> None:
    vid = uuid4()
    msg = CastMessage.model_validate({"type": "cast", "voteId": str(vid), "choice": "yes"})
    assert msg.vote_id == vid
    assert msg.choice == "yes"


def test_cast_message_rejects_empty_choice() -> None:
    with pytest.raises(ValidationError):
        CastMessage.model_validate({"type": "cast", "voteId": str(uuid4()), "choice": ""})


def test_subscribe_message() -> None:
    assert SubscribeMessage.model_validate({"type": "subscribe"}).type == "subscribe"
