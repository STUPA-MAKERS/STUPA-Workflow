"""A repeat meeting names its first meeting (§F/meetings/meetings/000940)."""

from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.livevote.repeat import (
    REPEAT_FIRST_INVALID,
    REPEAT_NEEDS_FIRST,
    first_meeting_id,
)
from app.modules.livevote.schemas import MeetingCreate, MeetingPatch
from app.modules.livevote.service import MeetingService
from app.shared.errors import ValidationProblem

GID = uuid4()
DAY = date(2026, 11, 20)


def _store(*meetings: Any) -> Any:
    """A session stand-in that answers `get` from the given meetings."""
    by_id = {m.id: m for m in meetings}

    async def get(_model: object, key: UUID) -> Any:
        return by_id.get(key)

    return SimpleNamespace(get=get)


def _meeting(**over: Any) -> Any:
    return SimpleNamespace(
        **{"id": uuid4(), "gremium_id": GID, "date": date(2026, 11, 6), **over}
    )


async def _first(db: Any, first_id: UUID | None, **over: Any) -> UUID | None:
    return await first_meeting_id(
        db, **{"kind": "repeat", "gremium_id": GID, "first_id": first_id, "day": DAY, **over}
    )


async def test_a_repeat_meeting_without_a_first_meeting_is_refused() -> None:
    """§F/meetings/meetings/000940: the request gets a 422 `repeat_needs_first_meeting`."""
    with pytest.raises(ValidationProblem) as raised:
        await _first(_store(), None)
    assert raised.value.status == 422
    assert raised.value.code == REPEAT_NEEDS_FIRST


async def test_the_first_meeting_is_an_earlier_meeting_of_the_same_gremium() -> None:
    """§F/meetings/meetings/000940: each other meeting gives `repeat_first_meeting_invalid`."""
    earlier, undated = _meeting(), _meeting(date=None)
    later = _meeting(date=date(2026, 11, 21))
    foreign = _meeting(gremium_id=uuid4())
    db = _store(earlier, undated, later, foreign)
    assert await _first(db, earlier.id) == earlier.id
    assert await _first(db, undated.id) == undated.id
    assert await _first(db, later.id, day=None) == later.id
    for first_id, over in (
        (uuid4(), {}),
        (later.id, {}),
        (foreign.id, {}),
        (earlier.id, {"meeting_id": earlier.id}),
    ):
        with pytest.raises(ValidationProblem) as raised:
            await _first(db, first_id, **over)
        assert raised.value.code == REPEAT_FIRST_INVALID


async def test_another_kind_stores_no_first_meeting() -> None:
    earlier = _meeting()
    assert await _first(_store(earlier), earlier.id, kind="ordinary") is None


def test_the_bodies_take_the_first_meeting() -> None:
    first = uuid4()
    body = MeetingCreate(
        gremiumId=GID,
        title="Wiederholung",
        date=DAY,
        startTime=time(18, 0),
        kind="repeat",
        repeatOfId=first,
    )
    assert body.repeat_of_id == first
    assert MeetingPatch(repeatOfId=first).repeat_of_id == first


async def test_a_patch_keeps_names_and_clears_the_first_meeting() -> None:
    """§F/meetings/meetings/000940: the patch stores the first meeting of a repeat meeting.

    A patch without `repeatOfId` keeps the stored one. A patch that names another one
    stores it. A meeting that is no repeat meeting any more stores none.
    """
    first, other = _meeting(), _meeting()
    meeting = _meeting(kind="repeat", date=DAY, repeat_of_id=first.id)
    service = MeetingService(_store(first, other, meeting))
    await service._apply_first_meeting(meeting, MeetingPatch(kind="repeat"))
    assert meeting.repeat_of_id == first.id
    await service._apply_first_meeting(meeting, MeetingPatch(repeatOfId=other.id))
    assert meeting.repeat_of_id == other.id
    with pytest.raises(ValidationProblem):
        await service._apply_first_meeting(
            meeting, MeetingPatch(repeatOfId=other.id, date=date(2026, 11, 1))
        )
    meeting.kind = "ordinary"
    await service._apply_first_meeting(meeting, MeetingPatch(kind="ordinary"))
    assert meeting.repeat_of_id is None
