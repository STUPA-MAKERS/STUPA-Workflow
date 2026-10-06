"""Votes with guests of a public meeting (#17), without a database.

Covers the second eligibility path `cast_guest`, the guest count in the tally, the
attendance that the close fixes, and the refusal of `guestsVote` on an application
vote. The integration test `test_public_meeting.py` runs the same rules on Postgres.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.voting.service import VotingService, guest_voter_sub
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, ValidationProblem
from tests._support.flow_fakes import fake_session, result
from tests.unit.modules.voting.test_voting_service_unit import (  # noqa: F401 - fixture
    GID,
    NOW,
    _config,
    _create_body,
    _FakeFlow,
    _patch_flow,
    _vote,
    _voter,
)


def _audits(db: Any) -> list[Any]:
    return [a for a in db.added if type(a).__name__ == "AuditEntry"]


def test_guest_voter_sub_and_config_rule() -> None:
    gid = uuid4()
    assert guest_voter_sub(gid) == f"guest:{gid}"
    with pytest.raises(ValueError, match="no quorum"):
        VoteConfig.model_validate(
            {
                "options": ["yes", "no"],
                "majorityRule": "simple",
                "guestsVote": True,
                "quorum": {"type": "percent", "value": 50},
            }
        )


async def test_application_vote_refuses_guests() -> None:
    body = _create_body(config=_config(guestsVote=True))
    with pytest.raises(ValidationProblem) as err:
        await VotingService(fake_session()).create(uuid4(), body, Principal(sub="m"))
    assert err.value.code == "guests_vote_unavailable"


@pytest.mark.parametrize("secret", [False, True])
async def test_cast_guest_open_and_secret(secret: bool) -> None:
    vote = _vote(meeting_id=uuid4(), config=_config(guestsVote=True, secret=secret))
    gid = uuid4()
    inserted = result(uuid4())  # the RETURNING of the ballot or of the marker
    # The audit hook reads two statements before the insert.
    db = fake_session(result(vote), result(), result(), inserted)
    out = await VotingService(db).cast_guest(vote.id, gid, "yes", now=NOW)
    assert out.status == "cast"
    [entry] = _audits(db)
    assert entry.action == "vote_cast" and entry.actor == f"guest:{gid}"
    assert "choice" not in entry.data
    # The secret path adds the identity-free ballot; the open path inserts directly.
    secret_rows = [a for a in db.added if type(a).__name__ == "SecretBallot"]
    assert len(secret_rows) == (1 if secret else 0)


async def test_cast_guest_twice_409() -> None:
    vote = _vote(meeting_id=uuid4(), config=_config(guestsVote=True))
    db = fake_session(result(vote), result())
    with pytest.raises(ConflictError) as err:
        await VotingService(db).cast_guest(vote.id, uuid4(), "yes", now=NOW)
    assert err.value.code == "already_voted"


@pytest.mark.parametrize(
    ("over", "error", "code"),
    [
        ({"status": "closed"}, ConflictError, "conflict"),
        ({"closes_at": NOW}, ConflictError, "conflict"),
        ({"config": _config()}, ForbiddenError, "vote_members_only"),
    ],
)
async def test_cast_guest_refusals(over: dict[str, Any], error: type[Exception], code: str) -> None:
    base: dict[str, Any] = {"meeting_id": uuid4(), "config": _config(guestsVote=True)}
    base.update(over)
    vote = _vote(**base)
    with pytest.raises(error) as err:
        await VotingService(fake_session(result(vote))).cast_guest(vote.id, uuid4(), "yes", now=NOW)
    assert err.value.code == code  # type: ignore[attr-defined]


async def test_cast_guest_unknown_option_422() -> None:
    vote = _vote(meeting_id=uuid4(), config=_config(guestsVote=True))
    with pytest.raises(ValidationProblem):
        await VotingService(fake_session(result(vote))).cast_guest(
            vote.id, uuid4(), "maybe", now=NOW
        )


async def test_tally_counts_admitted_and_departed_guest_voters() -> None:
    vote = _vote(meeting_id=uuid4(), config=_config(guestsVote=True))
    stay, gone = uuid4(), uuid4()
    db = fake_session(
        result(vote),
        result("yes", "yes"),
        result(stay),  # admitted guests
        result(f"guest:{stay}", f"guest:{gone}"),  # guest ballots
        result(),  # guest voted markers
    )
    # present members 2; no absent delegators.
    db.scalar_results = [2, 0]
    out = await VotingService(db).get(vote.id)
    assert out.guests_vote is True
    # 2 members + the admitted guest + the guest who voted and left.
    assert out.tally.present == 4 and out.tally.revealed is False
    assert (out.tally.present_members, out.tally.present_guests) == (2, 2)


async def test_tally_members_vote_shows_guests_but_does_not_wait_for_them() -> None:
    vote = _vote(meeting_id=uuid4())
    db = fake_session(result(vote), result("yes", "yes"))
    db.scalar_results = [2, 5, 0]
    out = await VotingService(db).get(vote.id)
    assert out.tally.present == 2 and out.tally.revealed is True
    assert out.tally.present_guests == 5


async def test_secret_vote_without_meeting_stays_hidden() -> None:
    vote = _vote(config=_config(secret=True))
    db = fake_session(result(vote), result())
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False and out.tally.present_members is None


async def test_closed_vote_reads_the_fixed_attendance() -> None:
    vote = _vote(meeting_id=uuid4(), status="closed", result="passed")
    vote.present_members, vote.present_guests = 19, 7
    db = fake_session(result(vote), result("yes"))
    out = await VotingService(db).get(vote.id)
    assert (out.tally.present_members, out.tally.present_guests) == (19, 7)


async def test_counts_without_meeting_are_zero() -> None:
    service = VotingService(fake_session())
    assert await service._admitted_guest_count(_vote()) == 0  # type: ignore[arg-type]
    assert await service._present_count(_vote()) == 0  # type: ignore[arg-type]


@pytest.mark.parametrize("guests_vote", [True, False])
async def test_close_fixes_attendance(
    _patch_flow: type[_FakeFlow],  # noqa: F811
    guests_vote: bool,
) -> None:
    vote = _vote(
        meeting_id=uuid4(),
        application_id=None,
        eligible_count=23,
        config=_config(guestsVote=guests_vote),
    )
    guest_rows = [result(*[uuid4() for _ in range(7)]), result(), result()] if guests_vote else []
    db = fake_session(result(vote), result("yes", "yes", "no"), *guest_rows)
    db.scalar_results = [19] if guests_vote else [19, 7]
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.result == "passed"
    assert (vote.present_members, vote.present_guests) == (19, 7)
    assert (out.tally.present_members, out.tally.present_guests) == (19, 7)
    assert vote.eligible_count == (26 if guests_vote else 23)
    assert out.tally.eligible == (26 if guests_vote else 23)


async def test_close_without_meeting_keeps_attendance_empty(
    _patch_flow: type[_FakeFlow],  # noqa: F811
) -> None:
    vote = _vote(application_id=None)
    db = fake_session(result(vote), result("yes"))
    out = await VotingService(db).close(vote.id, _voter(), now=NOW)
    assert out.tally.present_members is None
    assert GID  # the default gremium of the helpers


async def test_open_secret_meeting_vote_stays_hidden() -> None:
    vote = _vote(meeting_id=uuid4(), config=_config(secret=True, guestsVote=True))
    db = fake_session(result(vote), result("yes"))
    db.scalar_results = [1]
    out = await VotingService(db).get(vote.id)
    assert out.tally.revealed is False and out.tally.present == 1
