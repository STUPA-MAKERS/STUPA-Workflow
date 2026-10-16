"""Who reads, writes and configures a board, and who may be assigned on it.

* ``gremium`` — read and write: ``todo.write`` in the gremium, or the admin bypass;
  configure: ``todo.configure`` there, or the admin bypass.
* ``personal`` — the owner only, for both (no admin bypass).
* ``team`` — the holders of ``board.permission``, for both.

Read and write are one right: a reader of a board works on its cards. A board that
the caller cannot read answers 404, never 403. Every path obeys the OAuth scope cap:
a token without ``todo.write`` in its scope reads no board (scope ``todos:write``).

Assignees and mentions must be members of the board: the active members of the
gremium whose role holds ``todo.write``, the owner, or the holders of the team
permission.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import admin_bypass, gremium_ids_for
from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.todos.models import TodoBoard
from app.modules.todos.schemas import TodoMember
from app.shared.people import permission_holders, person_of

TODO_WRITE = "todo.write"
TODO_CONFIGURE = "todo.configure"


@dataclass(slots=True)
class ReadScope:
    """The boards that one principal reads, as a SQL condition on ``todo_board``.

    ``all_gremien`` is the admin bypass: every gremium board. ``team_permissions``
    are the permissions of the team boards that the principal holds.
    """

    all_gremien: bool = False
    gremium_ids: set[uuid.UUID] = field(default_factory=set)
    owner_id: uuid.UUID | None = None
    team_permissions: set[str] = field(default_factory=set)

    def condition(self) -> ColumnElement[bool]:
        """The ``WHERE`` part that keeps the readable boards."""
        parts: list[ColumnElement[bool]] = []
        if self.all_gremien:
            parts.append(TodoBoard.kind == "gremium")
        elif self.gremium_ids:
            parts.append(TodoBoard.gremium_id.in_(self.gremium_ids))
        if self.owner_id is not None:
            parts.append(TodoBoard.owner_id == self.owner_id)
        if self.team_permissions:
            parts.append(
                (TodoBoard.kind == "team") & TodoBoard.permission.in_(self.team_permissions)
            )
        return or_(*parts) if parts else false()

    def allows(self, board: TodoBoard) -> bool:
        """Tell if the board is in the scope (the same rule as ``condition``)."""
        if board.kind == "gremium":
            return self.all_gremien or board.gremium_id in self.gremium_ids
        if board.kind == "personal":
            return self.owner_id is not None and board.owner_id == self.owner_id
        return board.permission in self.team_permissions


class BoardAccess:
    """The board rules of one request. It caches the per-principal lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._me: dict[str, uuid.UUID | None] = {}
        self._gremien: dict[tuple[str, str], set[uuid.UUID]] = {}
        self._scopes: dict[str, ReadScope] = {}

    async def me(self, principal: Principal) -> uuid.UUID | None:
        """Return the account row id of the principal (None without a row)."""
        if principal.sub not in self._me:
            self._me[principal.sub] = await self.session.scalar(
                select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
            )
        return self._me[principal.sub]

    async def _gremium_ids(self, principal: Principal, perm: str) -> set[uuid.UUID]:
        key = (principal.sub, perm)
        if key not in self._gremien:
            self._gremien[key] = await gremium_ids_for(self.session, principal, perm)
        return self._gremien[key]

    async def scope(self, principal: Principal) -> ReadScope:
        """Return the read scope of the principal (empty for a token without the scope)."""
        if principal.sub in self._scopes:
            return self._scopes[principal.sub]
        scope = ReadScope()
        if principal.scope_allows(TODO_WRITE):
            scope.all_gremien = admin_bypass(principal, TODO_WRITE)
            if not scope.all_gremien:
                scope.gremium_ids = await self._gremium_ids(principal, TODO_WRITE)
            scope.owner_id = await self.me(principal)
            permissions = (
                await self.session.scalars(
                    select(TodoBoard.permission)
                    .where(TodoBoard.kind == "team", TodoBoard.permission.is_not(None))
                    .distinct()
                )
            ).all()
            scope.team_permissions = {p for p in permissions if p and principal.has(p)}
        self._scopes[principal.sub] = scope
        return scope

    async def can_read(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal reads (and so writes) the board."""
        if not principal.scope_allows(TODO_WRITE):
            return False
        if board.kind == "gremium":
            return admin_bypass(principal, TODO_WRITE) or board.gremium_id in (
                await self._gremium_ids(principal, TODO_WRITE)
            )
        if board.kind == "personal":
            return board.owner_id is not None and board.owner_id == await self.me(principal)
        return board.permission is not None and principal.has(board.permission)

    async def can_configure(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal edits the name, the columns and the labels."""
        if not principal.scope_allows(TODO_CONFIGURE) or not await self.can_read(board, principal):
            return False
        if board.kind != "gremium":
            return True
        return admin_bypass(principal, TODO_CONFIGURE) or board.gremium_id in (
            await self._gremium_ids(principal, TODO_CONFIGURE)
        )

    async def members(self, board: TodoBoard) -> list[TodoMember]:
        """Return the people that the board accepts as assignees, by name."""
        if board.kind == "personal":
            rows = (
                await self.session.execute(
                    select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                        PrincipalRow.id == board.owner_id
                    )
                )
            ).all()
        elif board.kind == "team":
            rows = await permission_holders(self.session, board.permission or "")
        else:
            now = datetime.now(UTC)
            rows = (
                await self.session.execute(
                    select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email)
                    .join(GremiumMembership, GremiumMembership.principal_id == PrincipalRow.id)
                    .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                    .where(
                        GremiumMembership.gremium_id == board.gremium_id,
                        or_(
                            GremiumMembership.valid_from.is_(None),
                            GremiumMembership.valid_from <= now,
                        ),
                        or_(
                            GremiumMembership.valid_until.is_(None),
                            GremiumMembership.valid_until > now,
                        ),
                        GremiumRole.permissions.contains([TODO_WRITE]),
                        PrincipalRow.active.is_(True),
                        PrincipalRow.merged_into.is_(None),
                    )
                    .distinct()
                )
            ).all()
        out: dict[uuid.UUID, TodoMember] = {}
        for pid, name, email in rows:
            ref = person_of(pid, name, email)
            out[pid] = TodoMember(principal_id=pid, display_name=ref.display_name)
        return sorted(
            out.values(), key=lambda m: ((m.display_name or "").casefold(), str(m.principal_id))
        )

    async def member_ids(self, board: TodoBoard) -> set[uuid.UUID]:
        """Return the ids of ``members``."""
        return {m.principal_id for m in await self.members(board)}
