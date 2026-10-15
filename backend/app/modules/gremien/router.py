"""Routes of the tab "Gremien" under ``/api/gremien``. Every route reads only.

``GET /gremien/overview`` lists the gremien that the caller sees. Every route of one
gremium (``/gremien/{id}/...``) first runs the gate ``access.require_gremium``: an
active member, ``gremium.view_all`` or the admin role, else 404 problem+json.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.gremien.access import require_gremium
from app.modules.gremien.schemas import (
    AttendanceOut,
    DecisionKind,
    DecisionPageOut,
    DecisionResultFilter,
    GremiumMeetingOut,
    GremiumMemberOut,
    GremiumOverviewOut,
    MemberAttendanceOut,
)
from app.modules.gremien.service import GremienService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/gremien", tags=["gremien"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"

ReaderDep = Annotated[Principal, Depends(require_principal())]


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: _PROBLEM for code in codes}


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
) -> AttendanceOut:
    """Give the attendance per member and month (``YYYY-MM``, at most 24 months).

    Without a range the matrix holds the last six months. A start after the end or a
    longer range gives 422 ``invalid_month_range``.
    """
    await require_gremium(db, principal, gremium_id)
    return await service.attendance(gremium_id, principal, from_month=from_month, to_month=to_month)


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
    return await service.member_attendance(gremium_id, principal_id, month)


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
    await require_gremium(db, principal, gremium_id)
    return await service.decisions(
        gremium_id, principal, cursor=cursor, q=q, result=result, kind=kind, since=since
    )
