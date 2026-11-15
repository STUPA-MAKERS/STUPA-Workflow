"""Routes of the tab "Gremien" under ``/api/committees``.

Every route reads, except ``PUT /committees/{id}/info``, the save of the Info tab
(gremium permission ``info.write``, see ``info``). The attendance export writes one
``export`` audit entry and nothing else.

``GET /committees/overview`` lists the gremien that the caller sees. Every route of one
gremium (``/committees/{id}/...``) first runs the gate ``access.require_gremium``: an
active member, ``gremium.view_all`` or the admin role, else 404 problem+json.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.policy import has_gremium_permission
from app.modules.gremien.access import require_gremium
from app.modules.gremien_overview import info as gremium_info
from app.modules.gremien_overview.attendance_export import attendance_export, export_workbook
from app.modules.gremien_overview.schemas import (
    AttendanceOut,
    DecisionKind,
    DecisionPageOut,
    DecisionResultFilter,
    GremiumInfoIn,
    GremiumInfoOut,
    GremiumMeetingOut,
    GremiumMemberOut,
    GremiumOverviewOut,
    MemberAttendanceOut,
)
from app.modules.gremien_overview.service import GremienService
from app.shared.errors import ForbiddenError, ProblemDetail, ValidationProblem
from app.shared.xlsx import XLSX_MEDIA_TYPE

router = APIRouter(prefix="/committees", tags=["gremien"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_FIRST_DAY = date(1900, 1, 1)
_LAST_DAY = date(2099, 12, 31)
_MONTH = r"^(19|20)\d{2}-(0[1-9]|1[0-2])$"

ReaderDep = Annotated[Principal, Depends(require_principal())]


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


def _service(db: DbSession, settings: SettingsDep) -> GremienService:
    return GremienService(db, settings.local_timezone)


ServiceDep = Annotated[GremienService, Depends(_service)]


@router.get("/overview", response_model=list[GremiumOverviewOut], responses=_errors(401))
async def gremien_overview(principal: ReaderDep, service: ServiceDep) -> list[GremiumOverviewOut]:
    """List the gremien that the caller sees, by name.

    A member sees the own gremien; ``gremium.view_all`` and the admin role see every
    gremium. ``isMember`` and ``roleName`` tell the own ones.
    """
    return await service.overview(principal)


@router.get(
    "/{gremium_id}/members",
    response_model=list[GremiumMemberOut],
    responses=_errors(401, 404),
)
async def gremium_members(
    gremium_id: UUID,
    principal: ReaderDep,
    db: DbSession,
    service: ServiceDep,
    former: bool = False,
) -> list[GremiumMemberOut]:
    """List the members of a gremium by role, or the former members with ``former=true``."""
    await require_gremium(db, principal, gremium_id)
    return await service.members(gremium_id, principal, former=former)


@router.get(
    "/{gremium_id}/meetings",
    response_model=list[GremiumMeetingOut],
    responses=_errors(401, 404),
)
async def gremium_meetings(
    gremium_id: UUID, principal: ReaderDep, db: DbSession, service: ServiceDep
) -> list[GremiumMeetingOut]:
    """List the meetings of a gremium, the newest first, with attendance and protocol state."""
    await require_gremium(db, principal, gremium_id)
    return await service.meetings(gremium_id)


@router.get(
    "/{gremium_id}/attendance",
    response_model=AttendanceOut,
    responses=_errors(401, 404, 422),
)
async def gremium_attendance(
    gremium_id: UUID,
    principal: ReaderDep,
    db: DbSession,
    service: ServiceDep,
    from_month: Annotated[str | None, Query(alias="from", pattern=_MONTH)] = None,
    to_month: Annotated[str | None, Query(alias="to", pattern=_MONTH)] = None,
    term: Annotated[date | None, Query()] = None,
) -> AttendanceOut:
    """Give the attendance per member and month (``YYYY-MM``, at most 24 months).

    Without a range the matrix holds the last six months. A start after the end or a
    longer range gives 422 ``invalid_month_range``. ``term`` is a day of the term whose
    unexcused absences the rows count, the current term without it. With ``term`` and
    without a range the matrix holds the months of this term. A day out of the range
    of the calendar gives 422 ``invalid_date_range``.
    """
    await require_gremium(db, principal, gremium_id)
    if term is not None and not _FIRST_DAY <= term <= _LAST_DAY:
        raise ValidationProblem("term is out of the calendar", code="invalid_date_range")
    return await service.attendance(
        gremium_id, principal, from_month=from_month, to_month=to_month, term=term
    )


@router.get(
    "/{gremium_id}/attendance/export.xlsx",
    responses=_errors(401, 403, 404, 422),
)
async def export_gremium_attendance(
    gremium_id: UUID,
    principal: ReaderDep,
    db: DbSession,
    first: Annotated[date, Query(alias="from")],
    last: Annotated[date, Query(alias="to")],
) -> Response:
    """Export the attendance of a date range as ``.xlsx``.

    The file counts the closed ordinary meetings from ``from`` to ``to`` (both days
    included): one row for each person with the number of meetings with the status
    present, and an own row for each pool substitute with the number of seats taken.
    The caller needs ``session.manage`` in the gremium (403). A start after the end
    gives 422 ``invalid_date_range``. The export writes an ``export`` audit entry.
    """
    await require_gremium(db, principal, gremium_id)
    if not await has_gremium_permission(db, principal, "session.manage", gremium_id):
        raise ForbiddenError("not allowed to export the attendance of this gremium")
    if not _FIRST_DAY <= first <= last <= _LAST_DAY:
        raise ValidationProblem("from must not lie after to", code="invalid_date_range")
    export = await attendance_export(db, gremium_id, first, last)
    await audit_record(
        db,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="attendance.xlsx",
        data={"gremiumId": str(gremium_id), "rows": len(export.rows)},
    )
    await db.commit()
    return Response(
        content=export_workbook(export),
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Content-Disposition": (
                f'attachment; filename="anwesenheit-{first.isoformat()}-{last.isoformat()}.xlsx"'
            )
        },
    )


@router.get(
    "/{gremium_id}/attendance/{principal_id}",
    response_model=MemberAttendanceOut,
    responses=_errors(401, 404, 422),
)
async def gremium_member_attendance(
    gremium_id: UUID,
    principal_id: UUID,
    principal: ReaderDep,
    db: DbSession,
    service: ServiceDep,
    month: Annotated[str, Query(pattern=_MONTH)],
) -> MemberAttendanceOut:
    """Give the closed meetings of one month with the state of one member.

    The state is present, excused, absent or delegated (with the delegate). The excuse
    text is never in the answer.
    """
    await require_gremium(db, principal, gremium_id)
    return await service.member_attendance(
        gremium_id, principal_id, month, requester_sub=principal.sub
    )


@router.get(
    "/{gremium_id}/decisions",
    response_model=DecisionPageOut,
    responses=_errors(400, 401, 404, 422),
)
async def gremium_decisions(
    gremium_id: UUID,
    principal: ReaderDep,
    db: DbSession,
    service: ServiceDep,
    cursor: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    result: DecisionResultFilter | None = None,
    kind: DecisionKind | None = None,
    since: date | None = None,
) -> DecisionPageOut:
    """List the closed votes of a gremium, the newest first, 30 per page.

    The read scope of the vote list applies. ``result`` (passed, rejected), ``kind``
    (application, election, motion), ``since`` (a day) and ``q`` (question or meeting
    title) filter.
    """
    if since is not None and not _FIRST_DAY <= since <= _LAST_DAY:
        raise ValidationProblem(
            f"since must lie between {_FIRST_DAY} and {_LAST_DAY}", code="invalid_since"
        )
    await require_gremium(db, principal, gremium_id)
    return await service.decisions(
        gremium_id, principal, cursor=cursor, q=q, result=result, kind=kind, since=since
    )


@router.get(
    "/{gremium_id}/info",
    response_model=GremiumInfoOut,
    responses=_errors(401, 404),
)
async def read_gremium_info(
    gremium_id: UUID, principal: ReaderDep, db: DbSession
) -> GremiumInfoOut:
    """Give the Info tab of a gremium: the Markdown text, the links and ``canEdit``.

    A gremium without a saved Info gives the empty Info with version 0.
    """
    await require_gremium(db, principal, gremium_id)
    return await gremium_info.read_info(db, principal, gremium_id)


@router.put(
    "/{gremium_id}/info",
    response_model=GremiumInfoOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def save_gremium_info(
    gremium_id: UUID, body: GremiumInfoIn, principal: ReaderDep, db: DbSession
) -> GremiumInfoOut:
    """Save the text and the links of the Info tab together.

    The caller needs ``info.write`` in the gremium (403). ``version`` is the version
    that the editor read: another version gives 409 ``gremium_info_version_conflict``.
    The save writes a ``gremium_info_update`` audit entry.
    """
    await require_gremium(db, principal, gremium_id)
    saved = await gremium_info.save_info(db, principal, gremium_id, body)
    await db.commit()
    return saved
