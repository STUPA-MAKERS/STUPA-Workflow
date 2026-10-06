"""The member list of one meeting (the roster).

The roster of a meeting is not the list of the members of the Gremium that are
valid now. A membership can end after the meeting, and the OIDC sync deletes the
membership rows of a principal who leaves a mapped group. A past meeting must
still show the people who attended it, and its counts must not change later.

The roster of a meeting therefore holds:

- each principal whose membership in the Gremium overlaps the meeting window,
- and each principal who has an attendance record for the meeting, also without
  a membership. A recorded attendance never disappears from the roster.

The meeting window goes from the real start (`started_at`), else the planned
start, to the close (`closed_at`) for a closed meeting, else to now. A planned
meeting in the future has the window "now". A closed meeting never uses "now"
when it has a start or a close time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, or_, select

from app.modules.admin.models import GremiumMembership
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.models import Meeting, MeetingAttendance


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


def meeting_window(
    meeting: Meeting, tz_name: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Return the meeting window `(start, end)` for the roster.

    - Start: `started_at`, else the planned start.
    - End: for a closed meeting `closed_at`, else the start. For a planned or live
      meeting, now.

    A start after the end (a planned meeting in the future) moves to the end. A
    meeting without any time gets the window "now".
    """
    now = now or datetime.now(UTC)
    # `getattr`: the protocol render also passes partial meeting objects.
    start = getattr(meeting, "started_at", None) or planned_start_utc(meeting, tz_name)
    closed_at = getattr(meeting, "closed_at", None)
    end = (closed_at or start or now) if getattr(meeting, "status", None) == "closed" else now
    if start is None or start > end:
        start = end
    return start, end


def roster_filter(
    gremium_id: UUID,
    start: datetime,
    end: datetime,
    *,
    meeting_id: UUID | None = None,
) -> ColumnElement[bool]:
    """Return the WHERE clause on `principal.id` that selects the roster.

    A membership counts when its half-open term `[valid_from, valid_until)`
    overlaps the window `[start, end]`. With `start == end` this is "valid at
    that time". With `meeting_id`, each principal with an attendance record for
    the meeting counts too. The clause uses two `IN` subqueries, so a single
    query gives each principal once.
    """
    members = select(GremiumMembership.principal_id).where(
        GremiumMembership.gremium_id == gremium_id,
        (GremiumMembership.valid_from.is_(None)) | (GremiumMembership.valid_from <= end),
        (GremiumMembership.valid_until.is_(None)) | (GremiumMembership.valid_until > start),
    )
    clauses: list[ColumnElement[bool]] = [PrincipalRow.id.in_(members)]
    if meeting_id is not None:
        recorded = select(MeetingAttendance.principal_id).where(
            MeetingAttendance.meeting_id == meeting_id
        )
        clauses.append(PrincipalRow.id.in_(recorded))
    return or_(*clauses)


def meeting_roster_filter(
    meeting: Meeting, tz_name: str, now: datetime | None = None
) -> ColumnElement[bool]:
    """Return the roster clause of one meeting: window members and recorded principals."""
    start, end = meeting_window(meeting, tz_name, now)
    return roster_filter(meeting.gremium_id, start, end, meeting_id=meeting.id)
