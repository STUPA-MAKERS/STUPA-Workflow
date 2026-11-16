"""The attendance export of a Gremium (§F/meetings/meetings/000923).

The Sitzungsgeld of a Semester is paid from this list. It counts the closed
``ordinary`` meetings of a date range:

- One row for each person with the number of meetings with the status ``present``. A
  meeting in which the person held a seat of the substitute pool does not count here.
- One own row for each pool substitute with the number of seats taken (the
  delegations ``via_pool`` of the range).

Every member of the Gremium has a row, also with the number 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations.models import MeetingDelegation
from app.modules.gremien.models import Gremium, GremiumMembership
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.meetings.periods import ORDINARY
from app.shared.xlsx import build_table_workbook

RowKind = Literal["member", "substitute"]

_KIND_LABEL: dict[RowKind, str] = {"member": "Mitglied", "substitute": "Vertretung (Pool)"}
_HEADERS = ("Name", "E-Mail", "Art", "Anwesend", "Sitze als Vertretung")


@dataclass(frozen=True, slots=True)
class ExportRow:
    """One row of the export: a person as a member, or as a pool substitute."""

    name: str
    email: str
    kind: RowKind
    count: int


@dataclass(frozen=True, slots=True)
class AttendanceExport:
    """The data of one export."""

    gremium_name: str
    first: date
    last: date
    meetings: int
    rows: tuple[ExportRow, ...]


def _in_range(gremium_id: UUID, first: date, last: date) -> ColumnElement[bool]:
    """Return the closed ordinary meetings of a gremium from ``first`` to ``last``."""
    return and_(
        Meeting.gremium_id == gremium_id,
        Meeting.status == "closed",
        Meeting.kind == ORDINARY,
        Meeting.date >= first,
        Meeting.date <= last,
    )


async def _present(session: AsyncSession, in_range: ColumnElement[bool]) -> dict[UUID, int]:
    """Count the meetings with ``present`` per person, without the pool seats."""
    seat = aliased(MeetingDelegation)
    pool_seat = exists().where(
        seat.meeting_id == MeetingAttendance.meeting_id,
        seat.delegate_principal_id == MeetingAttendance.principal_id,
        seat.via_pool.is_(True),
    )
    rows = await session.execute(
        select(MeetingAttendance.principal_id, func.count())
        .join(Meeting, Meeting.id == MeetingAttendance.meeting_id)
        .where(in_range, MeetingAttendance.status == "present", ~pool_seat)
        .group_by(MeetingAttendance.principal_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


async def _seats(session: AsyncSession, in_range: ColumnElement[bool]) -> dict[UUID, int]:
    """Count the pool seats per substitute."""
    rows = await session.execute(
        select(MeetingDelegation.delegate_principal_id, func.count())
        .join(Meeting, Meeting.id == MeetingDelegation.meeting_id)
        .where(in_range, MeetingDelegation.via_pool.is_(True))
        .group_by(MeetingDelegation.delegate_principal_id)
    )
    return {pid: int(n) for pid, n in rows.all()}


def _order(row: ExportRow) -> tuple[str, str, str]:
    return row.kind, row.name.casefold(), row.email


async def attendance_export(
    session: AsyncSession, gremium_id: UUID, first: date, last: date
) -> AttendanceExport:
    """Read the export of a gremium for the days from ``first`` to ``last``."""
    in_range = _in_range(gremium_id, first, last)
    meetings = await session.scalar(select(func.count()).select_from(Meeting).where(in_range))
    present = await _present(session, in_range)
    seats = await _seats(session, in_range)
    members = await session.scalars(
        select(GremiumMembership.principal_id).where(GremiumMembership.gremium_id == gremium_id)
    )
    member_ids = frozenset(members.all()) | present.keys()
    wanted = member_ids | seats.keys()
    found = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                PrincipalRow.id.in_(wanted)
            )
        )
        if wanted
        else None
    )
    people = {pid: (name or email or "", email or "") for pid, name, email in found or ()}
    rows = [
        *(
            ExportRow(*people.get(pid, ("", "")), kind="member", count=present.get(pid, 0))
            for pid in member_ids
        ),
        *(
            ExportRow(*people.get(pid, ("", "")), kind="substitute", count=n)
            for pid, n in seats.items()
        ),
    ]
    name = await session.scalar(select(Gremium.name).where(Gremium.id == gremium_id))
    return AttendanceExport(
        gremium_name=name or "",
        first=first,
        last=last,
        meetings=int(meetings or 0),
        rows=tuple(sorted(rows, key=_order)),
    )


def _cells(row: ExportRow) -> list[object]:
    member = row.kind == "member"
    return [
        row.name,
        row.email,
        _KIND_LABEL[row.kind],
        row.count if member else "",
        "" if member else row.count,
    ]


def export_workbook(export: AttendanceExport) -> bytes:
    """Build the export as ``.xlsx`` bytes."""
    day = "%d.%m.%Y"
    return build_table_workbook(
        title=f"Anwesenheit {export.gremium_name}".strip(),
        head=[
            ("Zeitraum", f"{export.first.strftime(day)} bis {export.last.strftime(day)}"),
            ("Ordentliche Sitzungen", str(export.meetings)),
        ],
        headers=_HEADERS,
        rows=[_cells(row) for row in export.rows],
    )
