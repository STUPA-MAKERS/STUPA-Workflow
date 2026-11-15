"""The one count of present members of a meeting (§F/meetings/meetings/000946).

The head of a meeting, its attendance list, its votes and its protocol show this count.
It is the count of the quorum (§F/meetings/voting/000900): each member with a voting
right and the attendance status `present`, and each pool substitute on a seat
(§F/meetings/delegations/000113). A person counts one time only. A member without a
voting right, a former member and a guest do not count.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.meetings.models import Meeting, MeetingAttendance

VOTE_PERMISSION = "vote.cast"


@dataclass(frozen=True, slots=True)
class Present:
    """The present count of one meeting, split for a vote that fixes the members."""

    #: The present members with a voting right.
    members: int = 0
    #: The pool substitutes on a seat who do not count as a present member.
    seats: int = 0

    @property
    def total(self) -> int:
        """Return the count that the meeting shows."""
        return self.members + self.seats


NOBODY = Present()


async def _present_voters(
    session: AsyncSession, meeting_ids: Sequence[UUID]
) -> dict[UUID, frozenset[UUID]]:
    """Return per meeting the present members whose gremium role holds `vote.cast`."""
    rows = (
        await session.execute(
            select(
                MeetingAttendance.meeting_id,
                MeetingAttendance.principal_id,
                GremiumRole.permissions,
            )
            .join(Meeting, Meeting.id == MeetingAttendance.meeting_id)
            .join(
                GremiumMembership,
                (GremiumMembership.principal_id == MeetingAttendance.principal_id)
                & (GremiumMembership.gremium_id == Meeting.gremium_id),
            )
            .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
            .where(
                MeetingAttendance.meeting_id.in_(meeting_ids),
                MeetingAttendance.status == "present",
            )
        )
    ).all()
    return {
        meeting_id: frozenset(
            pid
            for mid, pid, perms in rows
            if mid == meeting_id and VOTE_PERMISSION in (perms or [])
        )
        for meeting_id in {mid for mid, _, _ in rows}
    }


async def _seat_holders(
    session: AsyncSession, meeting_ids: Sequence[UUID]
) -> dict[UUID, frozenset[UUID]]:
    """Return per meeting the pool substitutes who hold a seat."""
    rows = (
        await session.execute(
            select(MeetingDelegation.meeting_id, MeetingDelegation.delegate_principal_id).where(
                MeetingDelegation.meeting_id.in_(meeting_ids),
                MeetingDelegation.via_pool.is_(True),
            )
        )
    ).all()
    return {
        meeting_id: frozenset(pid for mid, pid in rows if mid == meeting_id)
        for meeting_id in {mid for mid, _ in rows}
    }


async def present_counts(session: AsyncSession, meeting_ids: Sequence[UUID]) -> dict[UUID, Present]:
    """Return the present count of each meeting; a meeting without one is missing."""
    if not meeting_ids:
        return {}
    voters = await _present_voters(session, meeting_ids)
    holders = await _seat_holders(session, meeting_ids)
    return {
        meeting_id: Present(
            members=len(voters.get(meeting_id, frozenset())),
            seats=len(holders.get(meeting_id, frozenset()) - voters.get(meeting_id, frozenset())),
        )
        for meeting_id in voters.keys() | holders.keys()
    }


async def present_count(session: AsyncSession, meeting_id: UUID) -> Present:
    """Return the present count of one meeting."""
    return (await present_counts(session, [meeting_id])).get(meeting_id, NOBODY)


async def meeting_present(session: AsyncSession, meeting: Meeting) -> int:
    """Return the count that the meeting shows: fixed at the close, else counted now."""
    fixed: int | None = getattr(meeting, "present_count", None)
    if getattr(meeting, "status", None) == "closed" and fixed is not None:
        return fixed
    return (await present_count(session, meeting.id)).total


def fix_counts(meeting: Meeting, here: Present, eligible: int) -> None:
    """Store the present count and the member count of a closing meeting."""
    for column, value in (("present_count", here.total), ("eligible_count", eligible)):
        setattr(meeting, column, value)
