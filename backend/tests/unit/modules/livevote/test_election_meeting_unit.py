"""F2 · Personnel elections in a meeting, without a database.

Covers the election form of the vote open route, the open body rules, the candidate
account check, the reload path of the meeting votes, the WebSocket events of an
election and the beamer filter of the lot.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import LiveVoteConnection
from app.modules.livevote.events import (
    CastMessage,
    VoteClosedEvent,
    VoteOpenedEvent,
)
from app.modules.livevote.schemas import MeetingVoteOpenBody
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.voting.schemas import (
    ElectionLotOut,
    ElectionResultOut,
    TallyOut,
    VoteClosed,
    VoteOut,
)
from app.modules.voting.tally import encode_election_choice
from app.shared.config_schemas import ElectionConfig
from app.shared.errors import ValidationProblem
from tests.unit.modules.livevote.test_livevote_cov import (
    _FakeAgendaService,
    _FakeAttendanceService,
    _FakeVotingService,
    _QueueSession,
    _vote_row,
    res,
)
from tests.unit.modules.livevote.test_public_meeting_lead_unit import Guests, Meetings, _meeting

_ELECTION = ElectionConfig.model_validate(
    {
        "seats": 1,
        "candidates": [{"id": "c1", "name": "Anna"}, {"id": "c2", "name": "Ben"}],
    }
)


class _Meetings(Meetings):
    def __init__(self) -> None:
        super().__init__()
        self.checked: list[list[UUID]] = []

    async def assert_candidates_exist(self, principal_ids: list[UUID]) -> None:
        self.checked.append(principal_ids)


@pytest.fixture
def setup() -> Any:
    from fastapi.testclient import TestClient

    from app.deps import get_current_principal
    from app.main import create_app
    from app.modules.livevote import router

    meetings, agenda, voting = _Meetings(), _FakeAgendaService(), _FakeVotingService()
    app = create_app()
    app.dependency_overrides[router.get_meeting_service] = lambda: meetings
    app.dependency_overrides[router.get_attendance_service] = lambda: _FakeAttendanceService()
    app.dependency_overrides[router.get_agenda_service] = lambda: agenda
    app.dependency_overrides[router.get_voting_service] = lambda: voting
    app.dependency_overrides[router.get_guest_service] = lambda: Guests()
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="lead")
    return TestClient(app), meetings, agenda, voting


def _election_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agendaItemId": str(uuid4()),
        "kind": "election",
        "question": "Wahl der Sitzungsleitung",
        "seats": 1,
        "candidates": [{"name": " Anna "}, {"name": "Ben", "principalId": str(uuid4())}],
    }
    body.update(over)
    return body


def test_open_election_builds_the_election_config(setup: Any) -> None:
    client, meetings, agenda, voting = setup
    meetings._meeting_out = _meeting(True, "vote")
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=None, non_public=False)
    body = _election_body()
    resp = client.post(f"/api/meetings/{uuid4()}/votes", json=body)
    assert resp.status_code == 200, resp.text
    config = voting.last_payload.config
    assert isinstance(config, ElectionConfig)
    assert [c.id for c in config.candidates] == ["c1", "c2"]
    assert config.candidates[0].name == "Anna"
    assert [c.erased for c in config.candidates] == [False, False]
    assert config.secret is True
    # Guests vote in an election only when the lead switches them on.
    assert config.guests_vote is False
    assert voting.last_payload.eligible_count == 23
    assert meetings.checked == [[UUID(body["candidates"][1]["principalId"])]]


def test_open_election_keeps_an_explicit_secret_switch(setup: Any) -> None:
    client, meetings, agenda, voting = setup
    meetings._meeting_out = _meeting(False)
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=None, non_public=False)
    resp = client.post(
        f"/api/meetings/{uuid4()}/votes",
        json=_election_body(secret=False, candidates=[{"name": "A"}, {"name": "B"}]),
    )
    assert resp.status_code == 200, resp.text
    assert voting.last_payload.config.secret is False


def test_open_election_on_an_application_item_422(setup: Any) -> None:
    client, meetings, agenda, _ = setup
    meetings._meeting_out = _meeting(False)
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=uuid4(), non_public=False)
    resp = client.post(f"/api/meetings/{uuid4()}/votes", json=_election_body())
    assert resp.status_code == 422
    assert resp.json()["code"] == "election_on_application_item"


@pytest.mark.parametrize(
    "over",
    [
        {"question": "  "},
        {"seats": 3},
        {
            "candidates": [
                {"name": "A", "principalId": "00000000-0000-0000-0000-000000000001"},
                {"name": "B", "principalId": "00000000-0000-0000-0000-000000000001"},
            ]
        },
        {"candidates": [{"name": " "}]},
        # The client never sets the erasure marker nor the id of a candidate.
        {"candidates": [{"name": "A", "erased": True}, {"name": "B"}]},
        {"candidates": [{"name": "A", "erased": False}, {"name": "B"}]},
        {"candidates": [{"name": "A", "id": "c9"}, {"name": "B"}]},
        # A name without an account repeats another name (case and spaces ignored).
        {"candidates": [{"name": "Mara Schulz"}, {"name": " mara  SCHULZ "}]},
        {
            "candidates": [
                {"name": "Mara Schulz", "principalId": "00000000-0000-0000-0000-000000000001"},
                {"name": "Mara Schulz"},
            ]
        },
    ],
)
def test_open_body_rejects_a_bad_election(over: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        MeetingVoteOpenBody.model_validate(_election_body(**over))


def test_open_body_lets_two_accounts_share_a_name() -> None:
    body = MeetingVoteOpenBody.model_validate(
        _election_body(
            candidates=[
                {"name": "Anna Weber", "principalId": "00000000-0000-0000-0000-000000000001"},
                {"name": "Anna Weber", "principalId": "00000000-0000-0000-0000-000000000002"},
            ]
        )
    )
    assert [c["name"] for c in body.election_candidates()] == ["Anna Weber", "Anna Weber"]
    # The check lower-cases like the dialog: "Straße" and "STRASSE" are two names.
    body = MeetingVoteOpenBody.model_validate(
        _election_body(candidates=[{"name": "Straße"}, {"name": "STRASSE"}])
    )
    assert len(body.election_candidates()) == 2


def test_open_body_motion_ignores_the_election_fields() -> None:
    body = MeetingVoteOpenBody.model_validate({"agendaItemId": str(uuid4())})
    assert body.kind == "motion"
    assert body.secret is None
    assert body.election_candidates() == []


async def test_assert_candidates_exist_known_and_unknown() -> None:
    known, unknown = uuid4(), uuid4()
    svc = MeetingService(_QueueSession(executes=[res(known)]))  # type: ignore[arg-type]
    await svc.assert_candidates_exist([known])
    await MeetingService(_QueueSession()).assert_candidates_exist([])  # type: ignore[arg-type]
    svc = MeetingService(_QueueSession(executes=[res(known)]))  # type: ignore[arg-type]
    with pytest.raises(ValidationProblem) as err:
        await svc.assert_candidates_exist([known, unknown])
    assert err.value.code == "candidate_unknown"


def _election_row(**over: Any) -> Any:
    row = _vote_row(meeting_id=over.pop("meeting_id"), status=over.pop("status", "closed"))
    row.application_id = None
    row.kind = "election"
    row.round = 1
    row.parent_vote_id = None
    row.election_result = None
    row.present_members = None
    row.present_guests = None
    row.config = _ELECTION.model_dump(mode="json", by_alias=True)
    for key, value in over.items():
        setattr(row, key, value)
    return row


async def test_votes_for_reads_an_election() -> None:
    mid = uuid4()
    stored = ElectionResultOut(counts={"c1": 2, "c2": 1}, ballots=3, elected=["c1"])
    row = _election_row(
        meeting_id=mid,
        result="elected",
        election_result=stored.model_dump(mode="json", by_alias=True),
    )
    sess = _QueueSession(
        executes=[
            res(row),  # votes
            res(),  # open ballots of the motion tally
            res(),  # secret ballots of the motion tally
            res(),  # election: open ballots
            res(  # election: secret ballots
                (row.id, encode_election_choice(["c1"])),
                (row.id, encode_election_choice(["c1"])),
                (row.id, encode_election_choice(["c2"])),
            ),
            res((mid, 3)),  # present members
        ]
    )
    out = await MeetingService(sess)._votes_for([mid])  # type: ignore[arg-type]
    [item] = out[mid]
    assert item.kind == "election"
    assert item.voted == 3
    assert item.counts == {"c1": 2, "c2": 1, "abstain": 0}
    assert item.leading is None
    assert item.failed_reason is None
    assert item.election is not None and item.election.seats == 1
    assert item.election_result is not None and item.election_result.elected == ["c1"]


async def test_votes_for_marks_a_missed_quorum_of_an_election() -> None:
    mid = uuid4()
    config = {
        **_ELECTION.model_dump(mode="json", by_alias=True),
        "quorum": {"type": "count", "value": 5},
    }
    row = _election_row(meeting_id=mid, result="rejected", config=config)
    sess = _QueueSession(executes=[res(row), res(), res(), res(), res(), res((mid, 3))])
    [item] = (await MeetingService(sess)._votes_for([mid]))[mid]  # type: ignore[arg-type]
    assert item.failed_reason == "quorum"


async def test_election_tallies_without_elections() -> None:
    svc = MeetingService(_QueueSession())  # type: ignore[arg-type]
    assert await svc._election_tallies([]) == {}


async def test_ballots_of_decodes_an_election_ballot() -> None:
    mid = uuid4()
    row = _election_row(meeting_id=mid, status="open")
    sess = _QueueSession(
        executes=[res(), res((row.id, "me", encode_election_choice(["c2"]))), res()]
    )
    own, _ = await MeetingService(sess)._ballots_of("me", [row])  # type: ignore[arg-type]
    assert own[row.id].choices == ["c2"]


# ---------------------------------------------------------------- events


def _vote_out(**over: Any) -> VoteOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "meetingId": uuid4(),
        "eligibleGroup": "g",
        "config": _ELECTION.as_vote_config(),
        "status": "open",
        "secret": True,
        "tally": TallyOut(counts={}, eligible=5, quorumMet=True),
        "kind": "election",
        "election": _ELECTION,
        "round": 2,
    }
    base.update(over)
    return VoteOut.model_validate(base)


def test_vote_opened_event_carries_the_election() -> None:
    event: dict[str, Any] = VoteOpenedEvent.from_vote(_vote_out(), replay=True).dump()
    assert event["kind"] == "election"
    assert event["round"] == 2
    assert event["replay"] is True
    assert [c["name"] for c in event["election"]["candidates"]] == ["Anna", "Ben"]
    assert [c["erased"] for c in event["election"]["candidates"]] == [False, False]


def test_vote_opened_event_carries_the_erasure_marker() -> None:
    erased = ElectionConfig.model_validate(
        {
            "seats": 1,
            "candidates": [
                {"id": "c1", "name": "Gelöscht", "principalId": str(uuid4()), "erased": True},
                {"id": "c2", "name": "Ben"},
            ],
        }
    )
    vote = _vote_out(election=erased)
    assert [c["erased"] for c in vote.model_dump(by_alias=True)["election"]["candidates"]] == [
        True,
        False,
    ]
    event: dict[str, Any] = VoteOpenedEvent.from_vote(vote).dump()
    assert [c["erased"] for c in event["election"]["candidates"]] == [True, False]


def test_channel_events_carry_no_account_ids() -> None:
    """F2: the channel reaches the beamer and the guests: no principal id, no sub."""
    linked = ElectionConfig.model_validate(
        {
            "seats": 1,
            "candidates": [
                {"id": "c1", "name": "Anna", "principalId": str(uuid4())},
                {"id": "c2", "name": "Ben"},
            ],
        }
    )
    event: dict[str, Any] = VoteOpenedEvent.from_vote(_vote_out(election=linked)).dump()
    assert [c.get("principalId") for c in event["election"]["candidates"]] == [None, None]
    # A config without links stays as it is.
    assert _ELECTION.public() is _ELECTION
    result = ElectionResultOut(counts={}, lot=ElectionLotOut(among=["c1"], by="sub", byName="L"))
    lot = result.public().lot
    assert lot is not None
    assert lot.by is None
    assert lot.by_name == "L"
    plain = ElectionResultOut(counts={})
    assert plain.public() is plain


def test_cast_message_takes_a_list() -> None:
    msg = CastMessage.model_validate({"type": "cast", "voteId": str(uuid4()), "choice": []})
    assert msg.choice == []


async def test_publisher_sends_the_election_close_and_the_lot() -> None:
    broker = InMemoryBroker()
    vote = _vote_out(
        status="closed",
        result="elected",
        electionResult=ElectionResultOut(
            counts={"c1": 1, "c2": 1},
            elected=["c2"],
            lot=ElectionLotOut(among=["c1", "c2"], drawn=["c2"], by="sub-lead"),
        ),
    )
    closed = VoteClosed(
        id=vote.id,
        meetingId=vote.meeting_id,
        result="tie",
        tally=vote.tally,
        kind="election",
        electionResult=ElectionResultOut(
            counts={"c1": 1, "c2": 1}, lot=ElectionLotOut(among=["c1"], by="sub-lead")
        ),
    )
    pub = BrokerPublisher(broker)
    async with broker.subscribe(f"meeting:{vote.meeting_id}") as sub:
        await pub.vote_closed(closed)
        await pub.vote_lot_drawn(vote)
        # No meeting, or no result: nothing to send.
        await pub.vote_lot_drawn(vote.model_copy(update={"meeting_id": None}))
        await pub.vote_lot_drawn(vote.model_copy(update={"election_result": None}))
        first: dict[str, Any] = await anext(aiter(sub))
        second: dict[str, Any] = await anext(aiter(sub))
    assert first["type"] == "vote_closed" and first["kind"] == "election"
    assert first["result"] == "tie"
    assert second["type"] == "vote_lot_drawn"
    assert second["electionResult"]["lot"]["drawn"] == ["c2"]
    # No `sub` of the lead reaches the beamer or a guest.
    assert first["electionResult"]["lot"]["by"] is None
    assert second["electionResult"]["lot"]["by"] is None
    assert VoteClosedEvent.model_validate(first).election_result is not None


def test_beamer_gets_the_lot() -> None:
    beamer = LiveVoteConnection(
        SimpleNamespace(),  # type: ignore[arg-type]
        uuid4(),
        beamer=True,
        principal=SimpleNamespace(sub="p"),  # type: ignore[arg-type]
        meetings=SimpleNamespace(),  # type: ignore[arg-type]
        voting=SimpleNamespace(),  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        locker=SimpleNamespace(),  # type: ignore[arg-type]
        can_manage=True,
    )
    event: dict[str, object] = {"type": "vote_lot_drawn", "voteId": str(uuid4())}
    assert beamer._filter(event) == event
