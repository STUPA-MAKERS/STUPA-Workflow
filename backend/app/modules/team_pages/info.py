"""The Info tab of a free team (F/collaboration/teams/003077).

A member or a manager of a free team reads it; only a manager of the team (or the admin)
saves it. The text and the links have the shape of the Info of a Gremium, so the same
models check them. A save sends the version that the editor read: an older version gives
409 ``team_info_version_conflict``. Each save writes one ``team_info_update`` audit entry
with counts only, never the text or a link. An inherent team has no Info of its own: its
Gremium carries it (404 here).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien_overview.schemas import GremiumInfoIn, GremiumInfoLink, GremiumInfoOut
from app.modules.team_pages.service import TeamService
from app.modules.teams.models import TeamInfo
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError

VERSION_CONFLICT: Final = "team_info_version_conflict"


class TeamInfoService(TeamService):
    """The read and the save of the Info of a free team."""

    async def _free(self, team_id: UUID, principal: Principal) -> bool:
        """Check that the team is free and the caller reads it; return ``canEdit``.

        Raises:
            NotFoundError: No free team has the id (404).
            ForbiddenError: The caller is neither a member nor a manager (403).
        """
        team = await self._row(team_id)
        if team.gremium_id is not None:
            raise NotFoundError(f"team {team_id} has no info of its own")
        can_edit = await self.can_manage(team_id, principal)
        if not can_edit and team_id not in await self._my_teams(principal):
            raise ForbiddenError(
                "Only a member of the team reads its info.", code="team_member_required"
            )
        return can_edit

    async def _editor_name(self, principal_id: UUID | None) -> str | None:
        if principal_id is None:
            return None
        return (
            await self.session.execute(
                select(PrincipalRow.display_name).where(PrincipalRow.id == principal_id)
            )
        ).scalar_one_or_none()

    async def _out(self, row: TeamInfo | None, *, can_edit: bool) -> GremiumInfoOut:
        if row is None:
            return GremiumInfoOut(
                body_md="",
                links=(),
                version=0,
                updated_at=None,
                updated_by_name=None,
                can_edit=can_edit,
            )
        return GremiumInfoOut(
            body_md=row.body_md,
            links=tuple(GremiumInfoLink.model_validate(link) for link in row.links),
            version=row.version,
            updated_at=row.updated_at,
            updated_by_name=await self._editor_name(row.updated_by),
            can_edit=can_edit,
        )

    async def read_info(self, team_id: UUID, principal: Principal) -> GremiumInfoOut:
        """Return the Info of a free team with ``canEdit``; empty with version 0 unsaved."""
        can_edit = await self._free(team_id, principal)
        return await self._out(await self.session.get(TeamInfo, team_id), can_edit=can_edit)

    async def save_info(
        self, team_id: UUID, principal: Principal, body: GremiumInfoIn
    ) -> GremiumInfoOut:
        """Save text and links together and write the audit entry, without a commit.

        Raises:
            ForbiddenError: The caller does not manage the team (403
                ``team_manage_required``).
            ConflictError: ``version`` is not the stored version (409
                ``team_info_version_conflict``).
        """
        await self._free(team_id, principal)
        await self._require_manage(team_id, principal)
        row = (
            await self.session.execute(
                select(TeamInfo).where(TeamInfo.team_id == team_id).with_for_update()
            )
        ).scalar_one_or_none()
        stored = 0 if row is None else row.version
        if body.version != stored:
            raise ConflictError("the info changed since it was read", code=VERSION_CONFLICT)
        editor_id = (
            await self.session.execute(
                select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
            )
        ).scalar_one_or_none()
        values = {
            "body_md": body.body_md,
            "links": [link.model_dump() for link in body.links],
            "version": stored + 1,
            "updated_at": datetime.now(UTC),
            "updated_by": editor_id,
        }
        upsert = (
            pg_insert(TeamInfo)
            .values(team_id=team_id, **values)
            .on_conflict_do_update(index_elements=[TeamInfo.team_id], set_=values)
            .returning(TeamInfo)
            .execution_options(populate_existing=True)
        )
        target = (await self.session.execute(upsert)).scalar_one()
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.TEAM_INFO_UPDATE,
            target_type="team",
            target_id=str(team_id),
            data={
                "teamId": str(team_id),
                "version": target.version,
                "textLength": len(body.body_md),
                "links": len(body.links),
            },
        )
        return await self._out(target, can_edit=True)
