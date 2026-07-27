"""WS message schema test (T-16 DoD, api.md §4).

The tests pin the WS contract that the frontend (T-32, T-33) builds against: camelCase
field names and the ``type`` discriminator. The security-critical part: a tally event
and a closed event carry **only** aggregates (requirements N1a, no voter identity).
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
from app.modules.voting.schemas import TallyOut, VoteOut
from app.shared.config_schemas import VoteConfig


def _vote_out(*, secret: bool, status: str) -> VoteOut:
    return VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        meetingId=uuid4(),
        eligibleGroup="stupa",
        config=VoteConfig.model_validate(
            {"options": ["yes", "no"], "majorityRule": "simple", "secret": secret}
        ),
        status=status,  # type: ignore[arg-type]
        secret=secret,
        tally=TallyOut(
            counts={"yes": 5, "no": 3},
            eligible=12,
            voted=8,
            present=10,
            # The from_vote gate uses only ``revealed``. The service makes the
            # attendance-based reveal decision. A closed vote or a public vote shows.
            revealed=status == "closed" or not secret,
            quorumMet=True,
            leading="yes",
        ),
    )


def test_meeting_state_event_camel_and_optional_active() -> None:
    aid = uuid4()
    dumped = MeetingStateEvent(activeApplicationId=aid, status="live").dump()
    assert dumped == {
        "type": "meeting_state",
        "activeApplicationId": str(aid),
        "status": "live",
    }
    # Without an active application the field stays null and the beamer shows nothing.
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
    # A tally never carries a voter identity (requirements N1a).
    keys = set(dumped)
    assert not (keys & {"voter", "voterSub", "voters", "ballots", "names"})


def test_tally_from_open_secret_vote_hides_counts_shows_participation() -> None:
    # Security core (fix/secret-live-tally): an OPEN secret vote must not show a per
    # option interim count over the WS feed or the beamer feed. It shows the turnout.
    dumped = VoteTallyEvent.from_vote(_vote_out(secret=True, status="open")).dump()
    assert dumped["type"] == "vote_tally"
    assert dumped["secret"] is True
    assert dumped["counts"] == {}
    assert dumped["leading"] is None
    assert dumped["cast"] == 8                 # turnout only: 5 + 3 of 12
    assert dumped["eligible"] == 12
    # The raw choice counts (5 and 3) must not leak under ANY key.
    assert {3, 5}.isdisjoint(v for v in dumped.values() if type(v) is int)


def test_tally_from_closed_secret_vote_reveals_aggregates() -> None:
    # After the close the full aggregates appear. The rule: counts only at the close.
    dumped = VoteTallyEvent.from_vote(_vote_out(secret=True, status="closed")).dump()
    assert dumped["counts"] == {"yes": 5, "no": 3}
    assert dumped["leading"] == "yes"
    assert dumped["cast"] == 8


def test_tally_from_open_public_vote_shows_live_counts() -> None:
    # A public vote keeps the live interim count for the public bars.
    dumped = VoteTallyEvent.from_vote(_vote_out(secret=False, status="open")).dump()
    assert dumped["secret"] is False
    assert dumped["counts"] == {"yes": 5, "no": 3}
    assert dumped["leading"] == "yes"


def test_vote_opened_event_carries_secret_flag() -> None:
    dumped = VoteOpenedEvent(
        voteId=uuid4(), applicationId=uuid4(), options=["yes", "no"], secret=True
    ).dump()
    assert dumped["secret"] is True


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
