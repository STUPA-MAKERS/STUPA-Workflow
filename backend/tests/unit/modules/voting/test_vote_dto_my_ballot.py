"""A5: the vote DTOs carry the rules, the real times and the own ballot of the caller.

``VoteOut`` (``GET /votes/{id}``) and ``MeetingVoteOut`` (the meeting payload) add
``majorityRule``, ``secret``, ``quorum``, ``openedAt``, ``closedAt``, ``myBallot`` and
``representedCast``. A secret vote gives only ``myBallot.cast``, never the choice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.modules.livevote.schemas import MeetingVoteOut
from app.modules.livevote.service import MeetingService
from app.modules.voting.schemas import MyBallot, TallyOut, VoteOut
from app.shared.config_schemas import Quorum, VoteConfig
from tests.unit.modules.livevote.test_livevote_cov import _QueueSession, res

OPENED = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
CLOSED = datetime(2026, 10, 1, 10, 5, tzinfo=UTC)


def _row(*, meeting_id, gremium):  # noqa: ANN001, ANN202
    return SimpleNamespace(
        id=uuid4(),
        meeting_id=meeting_id,
        eligible_group=str(gremium),
    )


def test_vote_out_dumps_the_new_fields_in_camel_case() -> None:
    out = VoteOut(
        id=uuid4(),
        applicationId=uuid4(),
        eligibleGroup="g",
        config=VoteConfig.model_validate(
            {"options": ["yes", "no"], "majorityRule": "two_thirds"}
        ),
        status="closed",
        secret=True,
        majorityRule="two_thirds",
        quorum=Quorum(type="count", value=3),
        openedAt=OPENED,
        closedAt=CLOSED,
        tally=TallyOut(counts={}, eligible=3, quorumMet=True),
        myBallot=MyBallot(cast=True),
        representedCast=True,
    )
    dumped = out.model_dump(by_alias=True, mode="json")
    assert dumped["majorityRule"] == "two_thirds"
    assert dumped["quorum"] == {"type": "count", "value": 3}
    assert dumped["openedAt"].startswith("2026-10-01T10:00")
    assert dumped["closedAt"].startswith("2026-10-01T10:05")
    assert dumped["myBallot"] == {"cast": True, "choice": None, "choices": None}
    assert dumped["representedCast"] is True


def test_meeting_vote_out_defaults_have_no_ballot() -> None:
    out = MeetingVoteOut(id=uuid4(), status="open")
    assert out.my_ballot is None
    assert out.represented_cast is False
    assert out.closed_at is None


async def test_ballots_of_reads_own_choice_marker_and_represented() -> None:
    meeting, gremium = uuid4(), uuid4()
    open_vote = _row(meeting_id=meeting, gremium=gremium)
    secret_vote = _row(meeting_id=meeting, gremium=gremium)
    proxied = _row(meeting_id=meeting, gremium=gremium)
    untouched = _row(meeting_id=None, gremium=gremium)
    sess = _QueueSession(
        executes=[
            # The caller "me" holds a voting delegation of "boss" in this meeting.
            res((meeting, gremium, "boss")),
            # Own open ballot in open_vote; "boss" voted in proxied (open path).
            res((open_vote.id, "me", "yes"), (proxied.id, "boss", "no")),
            # Own voted marker in secret_vote (secret path, no choice); "boss" also
            # voted secretly in secret_vote.
            res((secret_vote.id, "me"), (secret_vote.id, "boss")),
        ]
    )
    svc = MeetingService(sess)  # type: ignore[arg-type]
    own, represented = await svc._ballots_of(
        "me",
        [open_vote, secret_vote, proxied, untouched],  # type: ignore[list-item]
    )
    assert own[open_vote.id] == MyBallot(cast=True, choice="yes")
    assert own[secret_vote.id] == MyBallot(cast=True, choice=None)
    assert proxied.id not in own
    assert untouched.id not in own
    # The represented ballot counts from the open ballot and from the voted marker.
    assert represented == {proxied.id, secret_vote.id}
