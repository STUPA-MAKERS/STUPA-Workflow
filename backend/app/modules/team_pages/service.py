"""The reads and writes of the teams (F/collaboration/teams/003060-003066, 003074).

Rights, checked here on the server:

* read — every signed-in person reads the list of the teams and the sub-teams of a
  team, because the picker of the boards and the Termine offers every team by name. The
  members of a team show only to its members, its managers and the admin.
* create — a team at the top needs ``team.create`` (or the admin role); a sub-team needs
  a manager of the parent (spec 003065). The creator becomes the first manager.
* manage — rename, move, delete and the members of a free team need a manager of the
  team: the role ``manager`` of a free team, the Gremium role with ``team.manage`` of
  an inherent team (spec 003066), or the admin role. A token needs ``team.manage`` in
  its scope.

An inherent team keeps its Gremium's name, has no parent, has no hand-made members and
goes only with its Gremium (spec 003061). A team with sub-teams is not deleted (spec
003062), and neither is a team whose board still holds cards, because the cards and
their files have no other place.

No method commits; the router commits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth import policy
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.people import person_of
from app.modules.auth.principal import Principal
from app.modules.team_pages.schemas import (
    TeamCreate,
    TeamDetailOut,
    TeamMemberIn,
    TeamMemberOut,
    TeamOut,
    TeamPatch,
)
from app.modules.teams.members import (
    TEAM_CREATE,
    TEAM_MANAGE,
    TeamInfo,
    managed_team_ids,
    member_ids_stmt,
    member_team_ids,
    team_infos,
)
from app.modules.teams.models import Team, TeamMember
from app.modules.todos.boards import ensure_team_board
from app.modules.todos.models import TodoBoard, TodoCard
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem


@dataclass(frozen=True)
class _Rights:
    """The teams of the caller, read once per request and forgotten after a write."""

    managed: frozenset[uuid.UUID] | None = None
    mine: frozenset[uuid.UUID] | None = None


class TeamService:
    """The team reads and writes of one request."""

    #: The frozen default is shared; a read replaces it on the instance.
    _rights: _Rights = _Rights()

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to the session of the request."""
        self.session = session

    def _forget(self) -> None:
        """Drop the read rights after a write that changes them."""
        self._rights = _Rights()

    # ----- rights -----

    async def _my_teams(self, principal: Principal) -> frozenset[uuid.UUID]:
        if self._rights.mine is None:
            self._rights = replace(
                self._rights, mine=await member_team_ids(self.session, principal)
            )
        return self._rights.mine or frozenset()

    async def can_manage(self, team_id: uuid.UUID, principal: Principal) -> bool:
        """Tell if the principal manages the team (own role or the admin role)."""
        if policy.admin_bypass(principal, TEAM_MANAGE):
            return True
        if not principal.scope_allows(TEAM_MANAGE):
            return False
        if self._rights.managed is None:
            self._rights = replace(
                self._rights, managed=await managed_team_ids(self.session, principal)
            )
        return team_id in (self._rights.managed or frozenset())

    async def _require_manage(self, team_id: uuid.UUID, principal: Principal) -> None:
        if not await self.can_manage(team_id, principal):
            raise ForbiddenError(
                "Only a manager of the team does this.", code="team_manage_required"
            )

    async def _row(self, team_id: uuid.UUID, *, lock: bool = False) -> Team:
        stmt = select(Team).where(Team.id == team_id)
        row = await self.session.scalar(
            (stmt.with_for_update() if lock else stmt).execution_options(populate_existing=True)
        )
        if row is None:
            raise NotFoundError(f"team {team_id} not found")
        return row

    # ----- reads -----

    async def _outs(self, infos: list[TeamInfo], principal: Principal) -> list[TeamOut]:
        boards = dict(
            (
                await self.session.execute(
                    select(TodoBoard.team_id, TodoBoard.id).where(
                        TodoBoard.team_id.in_([t.id for t in infos])
                    )
                )
            )
            .tuples()
            .all()
        )
        mine = await self._my_teams(principal)
        return [
            TeamOut(
                id=t.id,
                name=t.name,
                gremium_id=t.gremium_id,
                parent_id=t.parent_id,
                parent_name=t.parent_name,
                board_id=boards.get(t.id),
                is_member=t.id in mine,
                can_manage=await self.can_manage(t.id, principal),
            )
            for t in infos
        ]

    async def listing(self, principal: Principal) -> list[TeamOut]:
        """Every team by name, with the rights of the caller."""
        return await self._outs(await team_infos(self.session), principal)

    async def detail(self, team_id: uuid.UUID, principal: Principal) -> TeamDetailOut:
        """A team with its members (for members and managers) and its sub-teams.

        Raises:
            NotFoundError: No team has the id (404).
        """
        infos = await team_infos(self.session, ids=(team_id,))
        if not infos:
            raise NotFoundError(f"team {team_id} not found")
        team = (await self._outs(infos, principal))[0]
        children = list(
            (await self.session.scalars(select(Team.id).where(Team.parent_id == team_id))).all()
        )
        subs = await self._outs(await team_infos(self.session, ids=children), principal)
        shows = team.is_member or team.can_manage
        return TeamDetailOut(
            team=team,
            members=tuple(await self._members(team)) if shows else (),
            sub_teams=tuple(subs),
        )

    async def _members(self, team: TeamOut) -> list[TeamMemberOut]:
        roles = (
            dict(
                (
                    await self.session.execute(
                        select(TeamMember.principal_id, TeamMember.role).where(
                            TeamMember.team_id == team.id
                        )
                    )
                )
                .tuples()
                .all()
            )
            if team.gremium_id is None
            else {}
        )
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.id.in_(member_ids_stmt((team.id,)))
                )
            )
        ).all()
        outs = [
            TeamMemberOut(
                principal_id=pid,
                display_name=person_of(pid, name, email).display_name or "",
                role=roles.get(pid),  # pyright: ignore[reportArgumentType]
            )
            for pid, name, email in rows
        ]
        return sorted(outs, key=lambda m: (m.display_name.casefold(), str(m.principal_id)))

    # ----- writes -----

    async def _audit(self, principal: Principal, team_id: uuid.UUID, data: dict[str, str]) -> None:
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.CONFIG_CHANGE,
            target_type="team",
            target_id=str(team_id),
            data=data,
        )

    async def _ancestors(self, team_id: uuid.UUID) -> set[uuid.UUID]:
        """The team and every team above it, by one recursive query."""
        up = select(Team.id, Team.parent_id).where(Team.id == team_id).cte(recursive=True)
        above = aliased(Team)
        chain = up.union(select(above.id, above.parent_id).join(up, above.id == up.c.parent_id))
        return set((await self.session.scalars(select(chain.c.id))).all())

    async def _check_parent(
        self, parent_id: uuid.UUID | None, principal: Principal, *, moving: uuid.UUID | None
    ) -> None:
        """The caller may put a team under ``parent_id`` (or at the top for None)."""
        if parent_id is None:
            if not principal.has(TEAM_CREATE):
                raise ForbiddenError(
                    "A team at the top needs team.create.", code="team_create_required"
                )
            return
        await self._row(parent_id)
        await self._require_manage(parent_id, principal)
        if moving is not None and moving in await self._ancestors(parent_id):
            raise ValidationProblem(
                "A team cannot be under itself.",
                code="team_cycle",
                errors=[{"field": "parentId", "msg": "cycle"}],
            )

    async def create(self, payload: TeamCreate, principal: Principal) -> TeamDetailOut:
        """Create a free team with its board; the creator becomes its manager.

        Raises:
            ForbiddenError: No ``team.create`` for a team at the top, or no manager of
                the parent (403).
            NotFoundError: The parent does not exist (404).
        """
        await self._check_parent(payload.parent_id, principal, moving=None)
        me = await self.session.scalar(
            select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
        )
        name = payload.name.strip() or payload.name
        team = Team(id=uuid.uuid4(), name=name, parent_id=payload.parent_id)
        self.session.add(team)
        await self.session.flush()
        if me is not None:
            self.session.add(TeamMember(team_id=team.id, principal_id=me, role="manager"))
        await ensure_team_board(self.session, team.id, name)
        await self._audit(principal, team.id, {"op": "create"})
        await self.session.flush()
        self._forget()
        return await self.detail(team.id, principal)

    async def patch(
        self, team_id: uuid.UUID, payload: TeamPatch, principal: Principal
    ) -> TeamDetailOut:
        """Rename a free team or move a team under another parent.

        Raises:
            ForbiddenError: Not a manager of the team or of the new parent (403).
            ConflictError: An inherent team takes no name and no parent (409
                ``inherent_team``).
            ValidationProblem: The move makes a cycle (422 ``team_cycle``).
        """
        team = await self._row(team_id, lock=True)
        await self._require_manage(team_id, principal)
        fields = payload.model_fields_set
        if team.gremium_id is not None and (payload.name is not None or "parent_id" in fields):
            raise ConflictError("The team of a Gremium follows its Gremium.", code="inherent_team")
        moves = "parent_id" in fields and payload.parent_id != team.parent_id
        if moves:
            await self._check_parent(payload.parent_id, principal, moving=team.id)
        name = None if payload.name is None else (payload.name.strip() or team.name)
        changes = {
            **({"parent_id": payload.parent_id} if moves else {}),
            **({"name": name} if name is not None else {}),
        }
        if changes:
            await self.session.execute(update(Team).where(Team.id == team.id).values(**changes))
        if name is not None:
            await self.session.execute(
                update(TodoBoard).where(TodoBoard.team_id == team.id).values(name=name)
            )
        await self._audit(principal, team.id, {"op": "update"})
        await self.session.flush()
        return await self.detail(team.id, principal)

    async def delete(self, team_id: uuid.UUID, principal: Principal) -> None:
        """Delete a free team without sub-teams and without cards on its board.

        Raises:
            ForbiddenError: Not a manager of the team (403).
            ConflictError: An inherent team (``inherent_team``), a team with sub-teams
                (``team_has_sub_teams``) or a board with cards (``team_board_not_empty``)
                (409).
        """
        team = await self._row(team_id, lock=True)
        await self._require_manage(team_id, principal)
        if team.gremium_id is not None:
            raise ConflictError(
                "The team of a Gremium goes with its Gremium.", code="inherent_team"
            )
        if await self.session.scalar(select(Team.id).where(Team.parent_id == team.id).limit(1)):
            raise ConflictError("The team has sub-teams.", code="team_has_sub_teams")
        cards = await self.session.scalar(
            select(func.count())
            .select_from(TodoCard)
            .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
            .where(TodoBoard.team_id == team.id)
        )
        if cards:
            raise ConflictError("The board of the team holds cards.", code="team_board_not_empty")
        await self.session.execute(delete(Team).where(Team.id == team.id))
        await self._audit(principal, team.id, {"op": "delete"})

    async def _free_team(self, team_id: uuid.UUID, principal: Principal) -> Team:
        team = await self._row(team_id, lock=True)
        await self._require_manage(team_id, principal)
        if team.gremium_id is not None:
            raise ConflictError(
                "The members of the team of a Gremium come from the Gremium.", code="inherent_team"
            )
        return team

    async def _managers_left(self, team_id: uuid.UUID, without: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(TeamMember)
                .where(
                    TeamMember.team_id == team_id,
                    TeamMember.role == "manager",
                    TeamMember.principal_id != without,
                )
            )
            or 0
        )

    async def set_member(
        self,
        team_id: uuid.UUID,
        principal_id: uuid.UUID,
        payload: TeamMemberIn,
        principal: Principal,
    ) -> TeamDetailOut:
        """Add a person to a free team or change the role (spec 003063).

        Raises:
            ForbiddenError: Not a manager of the team (403).
            ConflictError: An inherent team (``inherent_team``), or the change takes the
                last manager (``last_manager``) (409).
            ValidationProblem: The person is unknown or not active (422).
        """
        team = await self._free_team(team_id, principal)
        person = await self.session.get(PrincipalRow, principal_id)
        if person is None or not person.active or person.merged_into is not None:
            raise ValidationProblem(
                "Unknown person.",
                code="team_member_unknown",
                errors=[{"field": "principalId", "msg": "unknown"}],
            )
        current = await self.session.get(TeamMember, (team.id, principal_id))
        if current is None:
            self.session.add(
                TeamMember(team_id=team.id, principal_id=principal_id, role=payload.role)
            )
        else:
            demoted = current.role == "manager" and payload.role != "manager"
            if demoted and not await self._managers_left(team.id, principal_id):
                raise ConflictError("The team needs a manager.", code="last_manager")
            await self.session.execute(
                update(TeamMember)
                .where(TeamMember.team_id == team.id, TeamMember.principal_id == principal_id)
                .values(role=payload.role)
            )
        await self._audit(principal, team.id, {"op": "member", "role": payload.role})
        await self.session.flush()
        self._forget()
        return await self.detail(team.id, principal)

    async def remove_member(
        self, team_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TeamDetailOut:
        """Remove a person from a free team; the last manager stays (409 ``last_manager``)."""
        team = await self._free_team(team_id, principal)
        current = await self.session.get(TeamMember, (team.id, principal_id))
        if current is None:
            raise NotFoundError("The person is not a member of the team.")
        if current.role == "manager" and not await self._managers_left(team.id, principal_id):
            raise ConflictError("The team needs a manager.", code="last_manager")
        await self.session.delete(current)
        await self._audit(principal, team.id, {"op": "member_remove"})
        await self.session.flush()
        self._forget()
        return await self.detail(team.id, principal)
