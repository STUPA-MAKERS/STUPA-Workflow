"""The first meeting of a Wiederholungssitzung (§F/meetings/meetings/000940).

A meeting of the kind `repeat` takes the lower quorum of its Gremium (spec 000902). It
must name the meeting that had no quorum, so that not each meeting can take this
quorum. The first meeting is an earlier meeting of the same Gremium.
"""

from __future__ import annotations

from datetime import date as _date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meetings.models import Meeting
from app.shared.errors import ValidationProblem

REPEAT_NEEDS_FIRST = "repeat_needs_first_meeting"
REPEAT_FIRST_INVALID = "repeat_first_meeting_invalid"


def _earlier(first: Meeting, day: _date | None) -> bool:
    """Tell if `first` is not after `day`; a missing date decides nothing."""
    return day is None or first.date is None or first.date <= day


async def first_meeting_id(
    session: AsyncSession,
    *,
    kind: str,
    gremium_id: UUID,
    first_id: UUID | None,
    day: _date | None,
    meeting_id: UUID | None = None,
) -> UUID | None:
    """Return the first meeting that a meeting of `kind` stores, after the checks.

    A meeting of another kind stores none. `meeting_id` is the repeat meeting itself
    on a change, and None on the create.

    Raises:
        ValidationProblem: A repeat meeting names no first meeting
            (`repeat_needs_first_meeting`), or the named meeting is unknown, of
            another Gremium, the meeting itself or a later meeting
            (`repeat_first_meeting_invalid`). The API answers 422.
    """
    if kind != "repeat":
        return None
    if first_id is None:
        raise ValidationProblem(
            "A repeat meeting must name its first meeting.", code=REPEAT_NEEDS_FIRST
        )
    first = await session.get(Meeting, first_id)
    if (
        first is None
        or first.gremium_id != gremium_id
        or first.id == meeting_id
        or not _earlier(first, day)
    ):
        raise ValidationProblem(
            "The first meeting must be an earlier meeting of the same Gremium.",
            code=REPEAT_FIRST_INVALID,
        )
    return first.id
