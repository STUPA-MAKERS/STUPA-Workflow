"""Polls in a meeting, without a database.

Covers the poll form of the vote open route, the open body rules, the reload path of
the meeting votes and the WebSocket events of a poll.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.events import CastMessage, VoteOpenedEvent, VoteTallyEvent
from app.modules.livevote.public_schemas import GuestBallotBody
from app.modules.livevote.schemas import MeetingVoteOpenBody
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.voting.schemas import PollResultOut, TallyOut, VoteClosed, VoteOut
from app.shared.config_schemas import PollConfig
from tests.unit.modules.livevote.test_election_meeting_unit import setup  # noqa: F401
from tests.unit.modules.livevote.test_livevote_cov import _QueueSession, _vote_row, res
from tests.unit.modules.livevote.test_public_meeting_lead_unit import _meeting

_POLL = PollConfig.model_validate(
    {
        "mode": "multi",
        "options": [{"id": "o1", "label": "A"}, {"id": "o2", "label": "B"}],
        "maxChoices": 2,
    }
)


def _poll_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agendaItemId": str(uuid4()),
        "kind": "poll",
        "question": "Wohin?",
        "poll": {"mode": "single", "options": [{"label": "A"}, {"label": "B"}]},
    }
    body.update(over)
    return body


def test_open_poll_builds_the_poll_config(setup: Any) -> None:  # noqa: F811
    client, meetings, agenda, voting = setup
    meetings._meeting_out = _meeting(True, "vote")
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=None, non_public=False)
    resp = client.post(
        f"/api/meetings/{uuid4()}/votes", json=_poll_body(secret=True, quorumPercent=50)
    )
    assert resp.status_code == 200, resp.text
    config = voting.last_payload.config
    assert isinstance(config, PollConfig)
    assert config.option_ids == ["o1", "o2"]
    assert config.secret is True
    assert config.guests_vote is True


def test_open_poll_without_secret_is_open(setup: Any) -> None:  # noqa: F811
    client, meetings, agenda, voting = setup
    meetings._meeting_out = _meeting(False)
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=None, non_public=False)
    resp = client.post(f"/api/meetings/{uuid4()}/votes", json=_poll_body())
    assert resp.status_code == 200, resp.text
    assert voting.last_payload.config.secret is False


def test_open_poll_on_an_application_item_422(setup: Any) -> None:  # noqa: F811
    client, meetings, agenda, _ = setup
    meetings._meeting_out = _meeting(False)
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=uuid4(), non_public=False)
    resp = client.post(f"/api/meetings/{uuid4()}/votes", json=_poll_body())
    assert resp.status_code == 422
    assert resp.json()["code"] == "poll_on_application_item"


def test_open_poll_with_bad_options_422(setup: Any) -> None:  # noqa: F811
    client, meetings, agenda, _ = setup
    meetings._meeting_out = _meeting(False)
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=None, non_public=False)
    body = _poll_body(poll={"mode": "date", "options": [{"label": "A"}, {"label": "B"}]})
    resp = client.post(f"/api/meetings/{uuid4()}/votes", json=body)
    assert resp.status_code == 422
    assert resp.json()["code"] == "poll_invalid"


@pytest.mark.parametrize(
    "over",
    [
        {"question": "  "},
        {"poll": None},
        {"kind": "motion"},
    ],
)
def test_open_body_rejects_a_bad_poll(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MeetingVoteOpenBody.model_validate(_poll_body(**over))


def _poll_row(**over: Any) -> Any:
    row = _vote_row(meeting_id=over.pop("meeting_id"), status=over.pop("status", "closed"))
    row.application_id = None
    row.kind = "poll"
    row.poll_result = None
    row.present_members = None
    row.present_guests = None
    row.config = _POLL.model_dump(mode="json", by_alias=True)
    for key, value in over.items():
        setattr(row, key, value)
    return row


async def test_votes_for_reads_a_closed_poll() -> None:
    mid = uuid4()
    stored = PollResultOut(counts={"o1": 2, "o2": 1}, ballots=3, order=["o1", "o2"], top=["o1"])
    row = _poll_row(
        meeting_id=mid, result=None, poll_result=stored.model_dump(mode="json", by_alias=True)
    )
    sess = _QueueSession(
        executes=[
            res(row),  # votes
            res(),  # open ballots of the motion tally
            res(),  # secret ballots of the motion tally
            res((row.id, '["o1"]'), (row.id, '["o1","o2"]'), (row.id, '["o1"]')),  # poll
            res(),  # poll: secret ballots
            res((mid, 3)),  # present members
        ]
    )
    [item] = (await MeetingService(sess)._votes_for([mid]))[mid]  # type: ignore[arg-type]
    assert item.kind == "poll"
    assert item.voted == 3
    assert item.counts == {"o1": 3, "o2": 1, "abstain": 0}
    assert item.leading is None
    assert item.failed_reason is None
    assert item.poll is not None and item.poll.mode == "multi"
    assert item.poll_result is not None and item.poll_result.top == ["o1"]


async def test_votes_for_hides_the_count_of_a_running_poll() -> None:
    mid = uuid4()
    row = _poll_row(meeting_id=mid, status="open", result=None)
    sess = _QueueSession(
        executes=[res(row), res(), res(), res((row.id, '["o1"]')), res(), res((mid, 3))]
    )
    [item] = (await MeetingService(sess)._votes_for([mid]))[mid]  # type: ignore[arg-type]
    assert item.voted == 1
    assert item.poll_result is None


async def test_poll_tallies_without_polls() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._poll_tallies([]) == {}


# ---------------------------------------------------------------- events


def _vote_out(**over: Any) -> VoteOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "meetingId": uuid4(),
        "eligibleGroup": "g",
        "config": _POLL.as_vote_config(),
        "status": "open",
        "secret": False,
        "tally": TallyOut(counts={"o1": 1}, eligible=5, voted=1, revealed=True, quorumMet=True),
        "kind": "poll",
        "poll": _POLL,
        "pollResult": PollResultOut(counts={"o1": 1, "o2": 0}, ballots=1),
    }
    base.update(over)
    return VoteOut.model_validate(base)


def test_vote_events_carry_the_poll() -> None:
    opened: dict[str, Any] = VoteOpenedEvent.from_vote(_vote_out()).dump()
    assert opened["kind"] == "poll"
    assert [o["label"] for o in opened["poll"]["options"]] == ["A", "B"]
    tally: dict[str, Any] = VoteTallyEvent.from_vote(_vote_out()).dump()
    assert tally["pollResult"]["counts"] == {"o1": 1, "o2": 0}
    hidden = _vote_out(
        tally=TallyOut(counts={}, eligible=5, voted=1, revealed=False, quorumMet=True)
    )
    assert VoteTallyEvent.from_vote(hidden).dump()["pollResult"] is None


def test_cast_message_and_guest_ballot_take_date_answers() -> None:
    msg = CastMessage.model_validate(
        {"type": "cast", "voteId": str(uuid4()), "choice": {"o1": "yes", "o2": "maybe"}}
    )
    assert msg.choice == {"o1": "yes", "o2": "maybe"}
    assert GuestBallotBody.model_validate({"choice": {"o1": "no"}}).choice == {"o1": "no"}
    with pytest.raises(ValidationError):
        GuestBallotBody.model_validate({"choice": {"o1": "perhaps"}})


async def test_publisher_sends_the_poll_close() -> None:
    broker = InMemoryBroker()
    vote = _vote_out(status="closed")
    closed = VoteClosed(
        id=vote.id,
        meetingId=vote.meeting_id,
        result=None,
        tally=vote.tally,
        kind="poll",
        pollResult=PollResultOut(counts={"o1": 1, "o2": 0}, top=["o1"]),
    )
    async with broker.subscribe(f"meeting:{vote.meeting_id}") as sub:
        await BrokerPublisher(broker).vote_closed(closed)
        event: dict[str, Any] = await anext(aiter(sub))
    assert event["type"] == "vote_closed"
    assert event["result"] is None
    assert event["pollResult"]["top"] == ["o1"]
