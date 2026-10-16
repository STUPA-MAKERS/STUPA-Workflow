"""Who reads, writes and configures a board, and who may be assigned on it.

* ``gremium`` — write: ``todo.write`` in the gremium, ``todo.all`` or the admin
  bypass; configure: ``todo.configure`` there, or the admin bypass.
* ``personal`` — the owner only, for read, write and configure (no admin bypass,
  no ``todo.all``, no ``todo.read_all``).
* ``team`` — write: the holders of ``board.permission`` or of ``todo.all``;
  configure: the holders of ``board.permission``.

Read is write, plus the global ``todo.read_all`` on every gremium and team board.
``todo.all`` and ``todo.read_all`` never configure and never make a member. A board
that the caller cannot read answers 404, never 403; a readable board that the
caller cannot write answers 403 ``todo_write_required`` to a write.

Every path obeys the OAuth scope cap. The native rights (the gremium ``todo.write``,
the owner, the team permission) need ``todo.write`` in the scope (``todos:write``);
``todo.all`` (``todos:write``) and ``todo.read_all`` (``read``) go through
``Principal.has``. A token whose scope holds none of the three reads no board.
Through ``todo.all`` or ``todo.read_all`` a team board also needs its own
permission in the scope (``scope_allows``), because the team permission guards the
board: an admin ``read`` token must not open the board "Plattform"
(``ticket.manage``), which a ``read`` token cannot reach. A cookie session lets
every permission through, so only a narrow token sees a difference.

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
#: Global: read and write every gremium and team board (never a personal one).
TODO_ALL = "todo.all"
#: Global: read every gremium and team board (never a personal one), no writes.
TODO_READ_ALL = "todo.read_all"
#: A token reads to-dos when its scope lets one of these through.
TODO_READ_KEYS: tuple[str, ...] = (TODO_WRITE, TODO_ALL, TODO_READ_ALL)


def token_reads(principal: Principal) -> bool:
    """Tell if the OAuth scope lets the principal read to-dos at all (the token gate)."""
    return any(principal.scope_allows(key) for key in TODO_READ_KEYS)


def reads_all(principal: Principal) -> bool:
    """Tell if the principal reads every gremium and team board (global key or bypass).

    A team board also needs ``global_reach`` (its permission in the token scope).
    """
    return principal.has(TODO_ALL) or principal.has(TODO_READ_ALL)


def global_reach(board: TodoBoard, principal: Principal) -> bool:
    """Tell if a global key (``todo.all``, ``todo.read_all``) may open the board.

    Never a personal board; a team board only when its permission is in the token
    scope (always for a cookie session).
    """
    if board.kind == "personal":
        return False
    return board.kind == "gremium" or principal.scope_allows(board.permission or "")


@dataclass(slots=True)
class ReadScope:
    """The boards that one principal reads, as a SQL condition on ``todo_board``.

    ``all_gremien`` is every gremium board (the admin bypass, ``todo.all`` or
    ``todo.read_all``), ``all_teams`` every team board (``todo.all`` or
    ``todo.read_all`` in a cookie session). ``team_permissions`` are the
    permissions of the team boards that the principal holds, or, for a token with a
    global key, that its scope lets through.
    """

    all_gremien: bool = False
    gremium_ids: set[uuid.UUID] = field(default_factory=set)
    owner_id: uuid.UUID | None = None
    team_permissions: set[str] = field(default_factory=set)
    all_teams: bool = False

    def condition(self) -> ColumnElement[bool]:
        """The ``WHERE`` part that keeps the readable boards."""
        parts: list[ColumnElement[bool]] = []
        if self.all_gremien:
            parts.append(TodoBoard.kind == "gremium")
        elif self.gremium_ids:
            parts.append(TodoBoard.gremium_id.in_(self.gremium_ids))
        if self.owner_id is not None:
            parts.append(TodoBoard.owner_id == self.owner_id)
        if self.all_teams:
            parts.append(TodoBoard.kind == "team")
        elif self.team_permissions:
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
        return self.all_teams or board.permission in self.team_permissions


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
        everything = reads_all(principal)
        native = principal.scope_allows(TODO_WRITE)
        if everything:
            scope.all_gremien = True
            # A token reaches a team board through the global key only when its
            # scope lets the team permission through (``global_reach``).
            scope.all_teams = principal.scope_permissions is None
        if native:
            scope.all_gremien = scope.all_gremien or admin_bypass(principal, TODO_WRITE)
            if not scope.all_gremien:
                scope.gremium_ids = await self._gremium_ids(principal, TODO_WRITE)
            scope.owner_id = await self.me(principal)
        if not scope.all_teams and (native or everything):
            permissions = (
                await self.session.scalars(
                    select(TodoBoard.permission)
                    .where(TodoBoard.kind == "team", TodoBoard.permission.is_not(None))
                    .distinct()
                )
            ).all()
            scope.team_permissions = {
                p
                for p in permissions
                if p
                and ((native and principal.has(p)) or (everything and principal.scope_allows(p)))
            }
        self._scopes[principal.sub] = scope
        return scope

    async def _native(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal works on the board by its own right (not ``todo.all``).

        The gremium ``todo.write`` (or the admin bypass), the owner or the team
        permission; all of them need ``todo.write`` in the token scope.
        """
        if not principal.scope_allows(TODO_WRITE):
            return False
        if board.kind == "gremium":
            return admin_bypass(principal, TODO_WRITE) or board.gremium_id in (
                await self._gremium_ids(principal, TODO_WRITE)
            )
        if board.kind == "personal":
            return board.owner_id is not None and board.owner_id == await self.me(principal)
        return board.permission is not None and principal.has(board.permission)

    async def can_write(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal works on the cards of the board (``todo.all`` included)."""
        if principal.has(TODO_ALL) and global_reach(board, principal):
            return True
        return await self._native(board, principal)

    async def can_read(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal reads the board: a writer, or ``todo.read_all``."""
        if reads_all(principal) and global_reach(board, principal):
            return True
        return await self._native(board, principal)

    async def can_configure(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal edits the name, the columns and the labels.

        ``todo.all`` and ``todo.read_all`` never configure: the right is the native
        one plus ``todo.configure`` in the gremium (or the admin bypass).
        """
        if not principal.scope_allows(TODO_CONFIGURE) or not await self._native(board, principal):
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
