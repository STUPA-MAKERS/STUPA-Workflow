"""The one count of present members of a meeting (§F/meetings/meetings/000946)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.meetings.present import (
    NOBODY,
    Present,
    fixed_present,
    meeting_present,
    present_count,
    present_counts,
    quorum_present,
)
from tests._support.flow_fakes import fake_session, result
from tests.unit.conftest import Presence


@pytest.mark.real_present
async def test_a_person_counts_one_time_and_only_with_a_voting_right() -> None:
    """§F/meetings/meetings/000946: 2 present voters and 1 seat of another person.

    The fake session returns, in order: the present members with the permissions of
    their role, and the holders of a pool seat. Rita holds no `vote.cast`. Ben is a
    present voter and holds a seat, so the seat adds nobody.
    """
    mid, other = uuid4(), uuid4()
    anna, ben, rita, sam = uuid4(), uuid4(), uuid4(), uuid4()
    db: Any = fake_session(
        result((mid, anna, ["vote.cast"]), (mid, ben, ["vote.cast"]), (mid, rita, None)),
        result((mid, sam), (mid, ben), (other, sam)),
    )
    counts = await present_counts(db, [mid, other])
    assert counts == {mid: Present(members=2, seats=1), other: Present(members=0, seats=1)}
    assert counts[mid].total == 3


@pytest.mark.real_present
async def test_no_meeting_reads_nothing() -> None:
    db: Any = fake_session()
    assert await present_counts(db, []) == {}


async def test_a_meeting_without_a_present_person_counts_nobody(presence: Presence) -> None:
    db: Any = fake_session()
    assert await present_count(db, uuid4()) == NOBODY
    presence.here = Present(members=4, seats=1)
    assert (await present_count(db, uuid4())).total == 5


async def test_a_closed_meeting_shows_the_count_of_its_close(presence: Presence) -> None:
    """§F/meetings/meetings/000946: the close fixes the count; before it, the count moves."""
    db: Any = fake_session()
    presence.here = Present(members=2)
    live: Any = SimpleNamespace(id=uuid4(), status="live", present_count=None)
    closed: Any = SimpleNamespace(id=uuid4(), status="closed", present_count=7)
    old: Any = SimpleNamespace(id=uuid4(), status="closed", present_count=None)
    assert await meeting_present(db, live) == 2
    assert await meeting_present(db, closed) == 7
    assert await meeting_present(db, old) == 2


@pytest.mark.parametrize(
    ("status", "members", "seats", "want"),
    [
        ("open", 9, 9, 5 + 2),
        ("closed", 3, 1, 3 + 1),
        ("closed", 3, None, 3 + 2),
        ("closed", None, None, 5 + 2),
        ("cancelled", 3, 1, 5 + 2),
    ],
)
def test_quorum_present_takes_the_fixed_values_of_a_closed_vote(
    status: str, members: int | None, seats: int | None, want: int
) -> None:
    """A closed vote counts what it fixed; the meeting of now fills what it has not."""
    vote = SimpleNamespace(status=status, present_members=members, present_seats=seats)
    assert quorum_present(fixed_present(vote), Present(members=5, seats=2)) == want
