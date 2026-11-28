"""The member list of one meeting (the roster).

The OIDC sync deletes the membership rows of a principal who leaves a mapped
group. A past meeting must still show the people who attended it.

The roster of a meeting therefore holds:

- each principal with a membership in the Gremium,
- each principal who has an attendance record for the meeting, also without
  a membership. A recorded attendance never disappears from the roster,
- and each delegate who holds a delegation with the voting right in the meeting, also
  without a membership (§F/meetings/delegations/003150).

A membership has no term, so the roster does not depend on the time of the
meeting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, or_, select

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import GremiumMembership
from app.modules.meetings.models import Meeting, MeetingAttendance


def planned_start_utc(meeting: Meeting, tz_name: str) -> datetime | None:
    """Return the planned start of the meeting as an aware UTC datetime.

    The database stores `date` and `start_time` as naive local time in `tz_name`.
    A meeting without a start time begins at 00:00 local time.

    Returns:
        The start in UTC, or None when the meeting has no date.
    """
    day = getattr(meeting, "date", None)
    if day is None:
        return None
    local = datetime.combine(day, getattr(meeting, "start_time", None) or _time(0, 0))
    return local.replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def roster_filter(gremium_id: UUID, *, meeting_id: UUID | None = None) -> ColumnElement[bool]:
    """Return the WHERE clause on `principal.id` that selects the roster.

    Each member of the Gremium counts. With `meeting_id`, each principal with an
    attendance record for the meeting and each delegate with the voting right in it
    count too. The clause uses `IN` subqueries, so a single query gives each principal
    once.
    """
    members = select(GremiumMembership.principal_id).where(
        GremiumMembership.gremium_id == gremium_id
    )
    recorded = (
        ()
        if meeting_id is None
        else (
            PrincipalRow.id.in_(
                select(MeetingAttendance.principal_id).where(
                    MeetingAttendance.meeting_id == meeting_id
                )
            ),
            PrincipalRow.id.in_(
                select(MeetingDelegation.delegate_principal_id).where(
                    MeetingDelegation.meeting_id == meeting_id,
                    MeetingDelegation.delegate_voting.is_(True),
                )
            ),
        )
    )
    return or_(PrincipalRow.id.in_(members), *recorded)


def meeting_roster_filter(meeting: Meeting) -> ColumnElement[bool]:
    """Return the roster clause of one meeting: members, recorded principals, delegates."""
    return roster_filter(meeting.gremium_id, meeting_id=meeting.id)
