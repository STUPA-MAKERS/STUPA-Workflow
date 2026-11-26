"""Routes of the teams under ``/api/teams`` (F/collaboration/teams/003074).

Every route needs a signed-in person. The rights of a write are object rules of the team
(``TeamService``): ``team.create`` for a team at the top, a manager of the parent for a
sub-team, a manager of the team for every other write. The router commits.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.deps import DbSession, Principal, require_principal
from app.modules.gremien_overview.schemas import GremiumInfoIn, GremiumInfoOut
from app.modules.team_pages.info import TeamInfoService
from app.modules.team_pages.schemas import (
    TeamCreate,
    TeamDetailOut,
    TeamMemberIn,
    TeamOut,
    TeamPatch,
)
from app.modules.team_pages.service import TeamService
from app.shared.errors import ProblemDetail

router = APIRouter(prefix="/teams", tags=["teams"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}

ReaderDep = Annotated[Principal, Depends(require_principal())]


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


@router.get("", response_model=list[TeamOut], responses=_errors(401))
async def list_teams(principal: ReaderDep, db: DbSession) -> list[TeamOut]:
    """Every team by name, with ``isMember`` and ``canManage`` of the caller."""
    return await TeamService(db).listing(principal)


@router.post(
    "",
    response_model=TeamDetailOut,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(401, 403, 404, 422),
)
async def create_team(payload: TeamCreate, principal: ReaderDep, db: DbSession) -> TeamDetailOut:
    """Create a free team; the creator becomes its manager (spec 003065)."""
    out = await TeamService(db).create(payload, principal)
    await db.commit()
    return out


@router.get("/{team_id}", response_model=TeamDetailOut, responses=_errors(401, 404))
async def get_team(team_id: UUID, principal: ReaderDep, db: DbSession) -> TeamDetailOut:
    """A team with its sub-teams, and its members for a member or a manager."""
    return await TeamService(db).detail(team_id, principal)


@router.patch(
    "/{team_id}", response_model=TeamDetailOut, responses=_errors(401, 403, 404, 409, 422)
)
async def patch_team(
    team_id: UUID, payload: TeamPatch, principal: ReaderDep, db: DbSession
) -> TeamDetailOut:
    """Rename a free team or move a team under another parent."""
    out = await TeamService(db).patch(team_id, payload, principal)
    await db.commit()
    return out


@router.delete(
    "/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(401, 403, 404, 409),
)
async def delete_team(team_id: UUID, principal: ReaderDep, db: DbSession) -> Response:
    """Delete a free team without sub-teams and without cards on its board."""
    await TeamService(db).delete(team_id, principal)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{team_id}/members/{principal_id}",
    response_model=TeamDetailOut,
    responses=_errors(401, 403, 404, 409, 422),
)
async def set_team_member(
    team_id: UUID, principal_id: UUID, payload: TeamMemberIn, principal: ReaderDep, db: DbSession
) -> TeamDetailOut:
    """Add a person to a free team or change the role (spec 003063)."""
    out = await TeamService(db).set_member(team_id, principal_id, payload, principal)
    await db.commit()
    return out


@router.delete(
    "/{team_id}/members/{principal_id}",
    response_model=TeamDetailOut,
    responses=_errors(401, 403, 404, 409),
)
async def remove_team_member(
    team_id: UUID, principal_id: UUID, principal: ReaderDep, db: DbSession
) -> TeamDetailOut:
    """Remove a person from a free team; the last manager stays."""
    out = await TeamService(db).remove_member(team_id, principal_id, principal)
    await db.commit()
    return out


@router.get("/{team_id}/info", response_model=GremiumInfoOut, responses=_errors(401, 403, 404))
async def read_team_info(team_id: UUID, principal: ReaderDep, db: DbSession) -> GremiumInfoOut:
    """Give the Info tab of a free team: the Markdown text, the links and ``canEdit``.

    A member or a manager reads it (403 else). An inherent team gives 404: its Gremium
    carries the Info. A team without a saved Info gives the empty Info with version 0.
    """
    return await TeamInfoService(db).read_info(team_id, principal)


@router.put(
    "/{team_id}/info", response_model=GremiumInfoOut, responses=_errors(401, 403, 404, 409, 422)
)
async def save_team_info(
    team_id: UUID, body: GremiumInfoIn, principal: ReaderDep, db: DbSession
) -> GremiumInfoOut:
    """Save the text and the links of the Info tab of a free team together.

    Only a manager of the team saves (403 ``team_manage_required``). ``version`` is the
    version that the editor read: another version gives 409 ``team_info_version_conflict``.
    The save writes a ``team_info_update`` audit entry.
    """
    saved = await TeamInfoService(db).save_info(team_id, principal, body)
    await db.commit()
    return saved
