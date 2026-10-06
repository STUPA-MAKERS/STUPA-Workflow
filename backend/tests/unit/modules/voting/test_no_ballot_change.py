"""O11: a ballot never changes after the cast.

A second cast of the same voter gives 409 with the code ``already_voted``. This holds
for an open vote, for a secret vote and for the live-vote WebSocket, which sends the
same code as an error frame. ``VoteConfig`` has no ``allowChange`` any more.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import LiveVoteConnection
from app.modules.livevote.locks import InMemoryLocker
from app.modules.voting.schemas import BallotAccepted
from app.modules.voting.service import ALREADY_VOTED, VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
GID = UUID("00000000-0000-0000-0000-0000000011a0")


def _vote(*, secret: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        application_id=uuid4(),
        meeting_id=None,
        eligible_group=str(GID),
        config={"options": ["yes", "no"], "majorityRule": "simple", "secret": secret},
        eligible_count=3,
        opens_at=NOW,
        closes_at=None,
        closed_at=None,
        status="open",
        result=None,
    )


def _voter() -> Principal:
    return Principal(sub="v1", groups={vote_group_key(GID)})


def test_vote_config_refuses_allow_change() -> None:
    with pytest.raises(ValidationError, match="allowChange"):
        VoteConfig.model_validate(
            {"options": ["yes", "no"], "majorityRule": "simple", "allowChange": True}
        )


def test_stored_config_drops_only_the_legacy_allow_change() -> None:
    """An old container can write allowChange during a deploy. A read must not 500."""
    config = VoteConfig.from_stored(
        {"options": ["yes", "no"], "majorityRule": "simple", "allowChange": True}
    )
    assert config.options == ["yes", "no"]
    with pytest.raises(ValidationError, match="other"):
        VoteConfig.from_stored(
            {"options": ["yes", "no"], "majorityRule": "simple", "other": 1}
        )


def test_service_reads_a_vote_with_a_legacy_allow_change() -> None:
    vote: Any = _vote(secret=False)
    vote.config = {**vote.config, "allowChange": True}
    assert VotingService._config(vote).majority_rule == "simple"


def test_ballot_accepted_has_only_the_cast_status() -> None:
    assert BallotAccepted().status == "cast"
    with pytest.raises(ValidationError):
        BallotAccepted.model_validate({"status": "changed"})


@pytest.mark.parametrize("secret", [False, True])
async def test_second_cast_gives_409_already_voted(secret: bool) -> None:
    vote = _vote(secret=secret)
    # The first cast inserts. The second cast finds the unique row and inserts nothing.
    db = fake_session(result(vote), result(SimpleNamespace(id=uuid4())))
    first = await VotingService(db).cast(vote.id, _voter(), "yes", now=NOW)
    assert first.status == "cast"
    db = fake_session(result(vote), result())
    with pytest.raises(ConflictError) as ei:
        await VotingService(db).cast(vote.id, _voter(), "no", now=NOW)
    assert ei.value.status == 409
    assert ei.value.code == ALREADY_VOTED == "already_voted"
    assert db.committed == 0
    # The open path never updates a ballot.
    assert all("DO UPDATE" not in str(stmt) for stmt in db.statements)


class _AlreadyVoted:
    """Fake VotingService: the vote belongs to the meeting, the cast is a duplicate."""

    def __init__(self, meeting_id: UUID) -> None:
        self.meeting_id = meeting_id
        self.rolled_back = 0
        self.session = self

    async def get(self, vote_id: UUID) -> Any:
        return SimpleNamespace(id=vote_id, meeting_id=self.meeting_id)

    async def cast(self, *_a: object, **_k: object) -> None:
        raise ConflictError("Already voted.", code=ALREADY_VOTED)

    async def rollback(self) -> None:
        self.rolled_back += 1

    async def scalar(self, _stmt: object) -> int:
        # The account check of the WebSocket cast: the account is active.
        return 1


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send_json(self, data: dict[str, object]) -> None:
        self.sent.append(data)


async def test_ws_second_cast_sends_already_voted() -> None:
    meeting_id = uuid4()
    voting = _AlreadyVoted(meeting_id)
    ws = _FakeWS()
    conn = LiveVoteConnection(
        ws,  # type: ignore[arg-type]
        meeting_id,
        beamer=False,
        principal=Principal(sub="v1"),
        meetings=object(),  # type: ignore[arg-type]
        voting=voting,  # type: ignore[arg-type]
        broker=InMemoryBroker(),
        locker=InMemoryLocker(),
    )
    await conn._handle_cast({"type": "cast", "voteId": str(uuid4()), "choice": "no"})
    assert ws.sent == [{"type": "error", "code": "already_voted"}]
    assert voting.rolled_back == 1
