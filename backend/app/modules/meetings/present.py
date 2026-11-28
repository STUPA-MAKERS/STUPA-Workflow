"""The one count of present members of a meeting (§F/meetings/meetings/000946).

The head of a meeting, its attendance list, its votes and its protocol show this count.
It is the count of the quorum (§F/meetings/voting/000900): each member with a voting
right and the attendance status `present`, and each present delegate
(§F/meetings/delegations/003151). A delegate holds a delegation with the voting right in
the meeting. The delegate is present with the attendance status `present`, or, as a pool
substitute on a seat (§F/meetings/delegations/000113), without a record. A person counts
one time only, also with several delegations. A member without a voting right, a former
member and a guest do not count.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    #: The present delegates who do not count as a present member.
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


@dataclass(frozen=True, slots=True)
class Delegates:
    """The delegates of one meeting: whom each one represents, and who holds a pool seat."""

    #: Per delegate the delegators whose voting right the delegate holds.
    represents: dict[UUID, tuple[UUID, ...]]
    #: The delegates on a pool seat (``via_pool``).
    seat_holders: frozenset[UUID]


async def meeting_delegates(
    session: AsyncSession, meeting_ids: Sequence[UUID]
) -> dict[UUID, Delegates]:
    """Return per meeting its delegates with the voting right; a meeting without one is missing.

    A delegation without the voting right is the history of an older rule and makes
    nobody a delegate (§F/meetings/delegations/002900).
    """
    rows = (
        await session.execute(
            select(
                MeetingDelegation.meeting_id,
                MeetingDelegation.delegate_principal_id,
                MeetingDelegation.delegator_principal_id,
                MeetingDelegation.via_pool,
            )
            .where(
                MeetingDelegation.meeting_id.in_(meeting_ids),
                MeetingDelegation.delegate_voting.is_(True),
            )
            .order_by(MeetingDelegation.created_at, MeetingDelegation.id)
        )
    ).all()
    found: dict[UUID, Delegates] = {}
    for meeting_id in dict.fromkeys(mid for mid, _, _, _ in rows):
        mine = [(d, r, pool) for mid, d, r, pool in rows if mid == meeting_id]
        found[meeting_id] = Delegates(
            represents={
                d: tuple(r for d2, r, _ in mine if d2 == d)
                for d in dict.fromkeys(d for d, _, _ in mine)
            },
            seat_holders=frozenset(d for d, _, pool in mine if pool),
        )
    return found


async def _statuses(
    session: AsyncSession, meeting_ids: Sequence[UUID]
) -> dict[UUID, dict[UUID, str]]:
    """Return per meeting the attendance status of each principal with a record."""
    rows = (
        await session.execute(
            select(
                MeetingAttendance.meeting_id,
                MeetingAttendance.principal_id,
                MeetingAttendance.status,
            ).where(MeetingAttendance.meeting_id.in_(meeting_ids))
        )
    ).all()
    found: dict[UUID, dict[UUID, str]] = {}
    for mid, pid, status in rows:
        found.setdefault(mid, {})[pid] = status
    return found


def delegate_status(
    delegates: Delegates, statuses: Mapping[UUID, str], principal_id: UUID
) -> str | None:
    """Return the attendance status of a delegate: the record, else `present` on a pool seat.

    A pool substitute takes a seat only in the live meeting, so a seat without a record
    means present (§F/meetings/delegations/003152).
    """
    status = statuses.get(principal_id)
    if status is None and principal_id in delegates.seat_holders:
        return "present"
    return status


def present_delegates(delegates: Delegates, statuses: Mapping[UUID, str]) -> frozenset[UUID]:
    """Return the delegates who are present."""
    return frozenset(
        d for d in delegates.represents if delegate_status(delegates, statuses, d) == "present"
    )


async def present_counts(session: AsyncSession, meeting_ids: Sequence[UUID]) -> dict[UUID, Present]:
    """Return the present count of each meeting; a meeting without one is missing."""
    if not meeting_ids:
        return {}
    voters = await _present_voters(session, meeting_ids)
    delegates = await meeting_delegates(session, meeting_ids)
    statuses = await _statuses(session, list(delegates)) if delegates else {}
    return {
        meeting_id: Present(
            members=len(voters.get(meeting_id, frozenset())),
            seats=len(
                present_delegates(delegates[meeting_id], statuses.get(meeting_id, {}))
                - voters.get(meeting_id, frozenset())
            )
            if meeting_id in delegates
            else 0,
        )
        for meeting_id in voters.keys() | delegates.keys()
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


def fixed_present(vote: object) -> tuple[int | None, int | None]:
    """Return the present members and the seats that a closed vote fixed.

    A vote that is not closed has none, and a vote that closed before a column existed
    has none for this column. ``vote`` is a ``voting.Vote``; this module does not import
    its model.
    """
    if getattr(vote, "status", None) != "closed":
        return None, None
    return getattr(vote, "present_members", None), getattr(vote, "present_seats", None)


def quorum_present(fixed: tuple[int | None, int | None], here: Present) -> int:
    """Return the present count that the quorum of a meeting vote compares.

    The count is the present members plus the present delegates. A value that
    the vote fixed at its close wins; ``here``, the count of the meeting now, fills each
    value that the vote does not have. This is the one place of the rule: the vote
    service and the reload path of a meeting call it.
    """
    members, seats = fixed
    return (here.members if members is None else members) + (here.seats if seats is None else seats)


def fix_counts(meeting: Meeting, here: Present, eligible: int) -> None:
    """Store the present count and the member count of a closing meeting."""
    for column, value in (("present_count", here.total), ("eligible_count", eligible)):
        setattr(meeting, column, value)
