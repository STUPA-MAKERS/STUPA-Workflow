"""The unexcused absences of a term (§F/meetings/meetings/000920 and 000921).

An unexcused absence is an attendance record with the status ``absent`` in a closed
``ordinary`` meeting. A member who transferred the vote for the meeting is not absent.
A meeting without a record of the member does not count: only the meeting lead sets
``absent``, so a person who joined the Gremium later has no absence in an older meeting.

A term (Amtszeit) starts on the first day of ``termStartMonth`` of the Gremium and runs
one year (§F/meetings/meetings/000948).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import (
    DEFAULT_TERM_START_MONTH,
    Gremium,
    GremiumMembership,
    GremiumRole,
)
from app.modules.meetings.models import Meeting, MeetingAttendance, MeetingSettings
from app.modules.meetings.periods import ORDINARY, term_end, term_start

MANAGE_PERMISSION = "session.manage"


@dataclass(frozen=True, slots=True)
class AbsenceNotice:
    """One member whose count of a term reached the limit, or the limit minus 1."""

    principal_id: UUID
    name: str
    count: int
    limit: int

    @property
    def reached(self) -> bool:
        """Tell whether the count reached the limit itself."""
        return self.count >= self.limit


def unexcused(gremium_id: UUID, first: date, end: date) -> tuple[ColumnElement[bool], ...]:
    """Return the conditions of an unexcused absence in ``[first, end)``.

    They filter a join of ``meeting_attendance`` and ``meeting``.
    """
    transferred = exists().where(
        MeetingDelegation.meeting_id == MeetingAttendance.meeting_id,
        MeetingDelegation.delegator_principal_id == MeetingAttendance.principal_id,
        MeetingDelegation.delegate_voting.is_(True),
    )
    return (
        Meeting.gremium_id == gremium_id,
        Meeting.status == "closed",
        Meeting.kind == ORDINARY,
        Meeting.date >= first,
        Meeting.date < end,
        MeetingAttendance.status == "absent",
        ~transferred,
    )


async def unexcused_counts(
    session: AsyncSession, gremium_id: UUID, first: date, end: date
) -> dict[UUID, int]:
    """Return the number of unexcused absences per principal in ``[first, end)``."""
    rows = await session.execute(
        select(MeetingAttendance.principal_id, func.count())
        .join(Meeting, Meeting.id == MeetingAttendance.meeting_id)
        .where(*unexcused(gremium_id, first, end))
        .group_by(MeetingAttendance.principal_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


async def gremium_term_month(session: AsyncSession, gremium_id: UUID) -> int:
    """Return the month in which a term of the Gremium starts."""
    stored = await session.scalar(select(Gremium.term_start_month).where(Gremium.id == gremium_id))
    return DEFAULT_TERM_START_MONTH if stored is None else int(stored)


async def absence_notices(
    session: AsyncSession, meeting: Meeting, settings: MeetingSettings
) -> list[AbsenceNotice]:
    """Return the members whose absence in ``meeting`` brings them to the limit.

    A notice is due when the count of the term of the meeting is the limit minus 1 or
    the limit. Only a closed ``ordinary`` meeting with a date gives notices, and only
    for the members with an unexcused absence in this meeting.
    """
    if meeting.status != "closed" or meeting.kind != ORDINARY or meeting.date is None:
        return []
    first = term_start(meeting.date, await gremium_term_month(session, meeting.gremium_id))
    conditions = unexcused(meeting.gremium_id, first, term_end(first))
    here = await session.scalars(
        select(MeetingAttendance.principal_id)
        .join(Meeting, Meeting.id == MeetingAttendance.meeting_id)
        .where(*conditions, Meeting.id == meeting.id)
    )
    absent_here = frozenset(here.all())
    if not absent_here:
        return []
    counts = await unexcused_counts(session, meeting.gremium_id, first, term_end(first))
    limit = settings.absence_limit
    due = {pid: n for pid, n in counts.items() if pid in absent_here and n in (limit - 1, limit)}
    if not due:
        return []
    people = await session.execute(
        select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
            PrincipalRow.id.in_(due)
        )
    )
    notices = [
        AbsenceNotice(principal_id=pid, name=name or email or "", count=due[pid], limit=limit)
        for pid, name, email in people.all()
    ]
    return sorted(notices, key=lambda n: (n.name.casefold(), str(n.principal_id)))


async def manager_emails(session: AsyncSession, gremium_id: UUID) -> list[str]:
    """Return the addresses of the persons with ``session.manage`` in the Gremium."""
    rows = await session.scalars(
        select(PrincipalRow.email)
        .join(GremiumMembership, GremiumMembership.principal_id == PrincipalRow.id)
        .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
        .where(
            GremiumMembership.gremium_id == gremium_id,
            GremiumRole.permissions.contains([MANAGE_PERMISSION]),
            PrincipalRow.email.is_not(None),
        )
    )
    return sorted({email for email in rows.all() if email})
