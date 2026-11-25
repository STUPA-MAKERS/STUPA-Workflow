"""Who reads, writes and configures a board, and who may be assigned on it.

A person has a role on a board: ``read``, ``edit`` or ``manage`` (spec 001062). Read
reads the board, edit also works on the cards, manage also changes the name, the
columns, the labels, the settings and the member entries.

* ``team`` — each member of the team edits, and each manager of the team manages (spec
  003067; ``app.modules.teams.members`` says who is a member and a manager). The extra
  entries of the board (``todo_board_entry``, spec 001077) add their roles. The admin
  bypass manages.
* ``free`` — the entries only (spec 001062); the admin bypass manages (spec 001064).
* ``personal`` — the owner only, as manager (no admin bypass, no ``todo.all``, no
  ``todo.read_all``).
* ``permission`` — the holders of ``board.permission``, as managers (spec 003073).

A team entry stands for the members of the team at the time of the read (spec 003068):
every check reads the memberships again, per request. A person whom several entries
cover gets the highest role.

``todo.all`` writes and ``todo.read_all`` reads the cards of every team, free and
permission board (spec 001066). Neither configures and neither makes a member. A board
that the caller cannot read answers 404, never 403; a readable board that the caller
cannot write answers 403 ``todo_write_required`` to a write.

Every path obeys the OAuth scope cap. The own roles (membership, entry, owner, board
permission) need ``todo.write`` in the scope (``todos:write``), a configure also
``todo.configure``; ``todo.all`` (``todos:write``) and ``todo.read_all`` (``read``) go
through ``Principal.has``. A token whose scope holds none of the three reads no board.
Through ``todo.all`` or ``todo.read_all`` a permission board also needs its own
permission in the scope (``scope_allows``), because that permission guards the board: an
admin ``read`` token must not open the board "Plattform" (``ticket.manage``), which a
``read`` token cannot reach. A cookie session lets every permission through, so only a
narrow token sees a difference.

Assignees and mentions must be members of the board: the persons with ``edit`` or
``manage`` (spec 001065).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import policy
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.people import permission_holders, person_of
from app.modules.auth.principal import Principal
from app.modules.gremien.models import GremiumMembership
from app.modules.teams.members import (
    gremien_of_teams,
    managed_team_ids,
    member_ids_stmt,
    member_team_ids,
)
from app.modules.todos.models import TodoBoard, TodoBoardEntry
from app.modules.todos.schemas import TodoMember

TODO_WRITE = "todo.write"
TODO_CONFIGURE = "todo.configure"
#: Global: read and write every team, free and permission board (never a personal one).
TODO_ALL = "todo.all"
#: Global: read every team, free and permission board (never a personal one), no writes.
TODO_READ_ALL = "todo.read_all"
#: Global: create a free board (spec 001061).
TODO_CREATE_BOARD = "todo.create_board"
#: A token reads to-dos when its scope lets one of these through.
TODO_READ_KEYS: tuple[str, ...] = (TODO_WRITE, TODO_ALL, TODO_READ_ALL)

#: The rank of each role; 0 is no role.
ROLE_RANK: Mapping[str, int] = {"read": 1, "edit": 2, "manage": 3}
READ = 1
EDIT = 2
MANAGE = 3
#: The board kinds that ``todo.all`` and ``todo.read_all`` reach without a scope check.
SHARED_KINDS: tuple[str, ...] = ("team", "free")

type MemberRow = tuple[uuid.UUID, str | None, str | None]


def token_reads(principal: Principal) -> bool:
    """Tell if the OAuth scope lets the principal read to-dos at all (the token gate)."""
    return any(principal.scope_allows(key) for key in TODO_READ_KEYS)


def reads_all(principal: Principal) -> bool:
    """Tell if the principal reads every team, free and permission board (global key).

    A permission board also needs ``global_reach`` (its permission in the token scope).
    """
    return principal.has(TODO_ALL) or principal.has(TODO_READ_ALL)


def global_reach(board: TodoBoard, principal: Principal) -> bool:
    """Tell if a global key (``todo.all``, ``todo.read_all``) may open the board.

    Never a personal board; a permission board only when its permission is in the token
    scope (always for a cookie session).
    """
    if board.kind == "personal":
        return False
    return board.kind in SHARED_KINDS or principal.scope_allows(board.permission or "")


def can_create_board(principal: Principal) -> bool:
    """Tell if the principal creates a free board: ``todo.create_board`` or an admin."""
    return principal.has(TODO_CREATE_BOARD)


async def member_gremium_ids(session: AsyncSession, principal: Principal) -> frozenset[uuid.UUID]:
    """The gremien where the principal is an active member, read now."""
    rows = await session.scalars(
        select(GremiumMembership.gremium_id)
        .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
        .where(
            PrincipalRow.sub == principal.sub,
            PrincipalRow.active.is_(True),
            PrincipalRow.merged_into.is_(None),
        )
    )
    return frozenset(rows.all())


async def entry_roles(
    session: AsyncSession, me: uuid.UUID | None, teams: AbstractSet[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """The best role per board from the entries of ``me`` and of the teams of ``me``."""
    targets = (
        *((TodoBoardEntry.principal_id == me,) if me is not None else ()),
        *((TodoBoardEntry.team_id.in_(teams),) if teams else ()),
    )
    if not targets:
        return {}
    pairs = (
        (
            await session.execute(
                select(TodoBoardEntry.board_id, TodoBoardEntry.role).where(or_(*targets))
            )
        )
        .tuples()
        .all()
    )
    return {
        board_id: max(ROLE_RANK.get(role, 0) for other, role in pairs if other == board_id)
        for board_id in {board_id for board_id, _ in pairs}
    }


@dataclass(frozen=True, slots=True)
class ReadScope:
    """The boards that one principal reads, as a SQL condition on ``todo_board``.

    ``all_shared`` is every team and free board (the admin bypass, ``todo.all`` or
    ``todo.read_all``), ``all_permissions`` every permission board (``todo.all`` or
    ``todo.read_all`` in a cookie session). ``team_ids`` are the teams of the principal
    (their own boards), ``board_ids`` the boards of its entries. ``permissions`` are the
    permissions of the permission boards that the principal holds, or, for a token with a
    global key, that its scope lets through.
    """

    all_shared: bool = False
    team_ids: AbstractSet[uuid.UUID] = frozenset()
    owner_id: uuid.UUID | None = None
    permissions: AbstractSet[str] = frozenset()
    all_permissions: bool = False
    board_ids: AbstractSet[uuid.UUID] = frozenset()

    def _shared_part(self) -> tuple[ColumnElement[bool], ...]:
        if self.all_shared:
            return (TodoBoard.kind.in_(SHARED_KINDS),)
        own = (
            ((TodoBoard.kind == "team") & TodoBoard.team_id.in_(self.team_ids),)
            if self.team_ids
            else ()
        )
        entries = (TodoBoard.id.in_(self.board_ids),) if self.board_ids else ()
        return (*own, *entries)

    def _permission_part(self) -> tuple[ColumnElement[bool], ...]:
        if self.all_permissions:
            return (TodoBoard.kind == "permission",)
        return (
            ((TodoBoard.kind == "permission") & TodoBoard.permission.in_(self.permissions),)
            if self.permissions
            else ()
        )

    def condition(self) -> ColumnElement[bool]:
        """The ``WHERE`` part that keeps the readable boards that are not archived.

        An archived board shows in no list, no search and no cross-board read (spec
        001068); its own page still opens through ``BoardAccess.can_read``.
        """
        owner = (TodoBoard.owner_id == self.owner_id,) if self.owner_id is not None else ()
        parts = (*self._shared_part(), *owner, *self._permission_part())
        return and_(or_(*parts), TodoBoard.archived_at.is_(None)) if parts else false()

    def allows(self, board: TodoBoard) -> bool:
        """Tell if the board is in the scope (the same rule as ``condition``)."""
        match board.kind:
            case "personal":
                return self.owner_id is not None and board.owner_id == self.owner_id
            case "permission":
                return self.all_permissions or board.permission in self.permissions
            case "team":
                return (
                    self.all_shared or board.team_id in self.team_ids or board.id in self.board_ids
                )
            case _:
                return self.all_shared or board.id in self.board_ids


type _CacheKey = tuple[str, bool, frozenset[str] | None]


def _cache_key(principal: Principal) -> _CacheKey:
    """Return the cache key of a principal: the subject, the admin flag and the scope cap."""
    return (principal.sub, principal.is_admin, principal.scope_permissions)


class BoardAccess:
    """The board rules of one request. It caches the per-principal lookups."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the access check to a session; the rights are cached per instance."""
        self.session = session
        self._me: dict[str, uuid.UUID | None] = {}
        self._teams: dict[_CacheKey, frozenset[uuid.UUID]] = {}
        self._managed: dict[_CacheKey, frozenset[uuid.UUID]] = {}
        self._entries: dict[_CacheKey, dict[uuid.UUID, int]] = {}
        self._scopes: dict[_CacheKey, ReadScope] = {}

    async def me(self, principal: Principal) -> uuid.UUID | None:
        """Return the account row id of the principal (None without a row)."""
        if principal.sub not in self._me:
            self._me[principal.sub] = await self.session.scalar(
                select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
            )
        return self._me[principal.sub]

    async def _member_of(self, principal: Principal) -> frozenset[uuid.UUID]:
        """The teams of the principal; empty when the scope lacks ``todo.write``."""
        if _cache_key(principal) not in self._teams:
            self._teams[_cache_key(principal)] = (
                await member_team_ids(self.session, principal)
                if principal.scope_allows(TODO_WRITE)
                else frozenset()
            )
        return self._teams[_cache_key(principal)]

    async def _manages(self, principal: Principal) -> frozenset[uuid.UUID]:
        """The teams that the principal manages by an own role (no bypass)."""
        if _cache_key(principal) not in self._managed:
            self._managed[_cache_key(principal)] = await managed_team_ids(self.session, principal)
        return self._managed[_cache_key(principal)]

    async def _entry_roles(self, principal: Principal) -> dict[uuid.UUID, int]:
        """The best entry role per board; empty when the scope lacks ``todo.write``."""
        if _cache_key(principal) not in self._entries:
            self._entries[_cache_key(principal)] = (
                await entry_roles(
                    self.session, await self.me(principal), await self._member_of(principal)
                )
                if principal.scope_allows(TODO_WRITE)
                else {}
            )
        return self._entries[_cache_key(principal)]

    async def scope(self, principal: Principal) -> ReadScope:
        """Return the read scope of the principal (empty for a token without the scope).

        A token reaches a permission board through the global key only when its scope
        lets that permission through (``global_reach``).
        """
        if _cache_key(principal) in self._scopes:
            return self._scopes[_cache_key(principal)]
        everything = reads_all(principal)
        native = principal.scope_allows(TODO_WRITE)
        all_permissions = everything and principal.scope_permissions is None
        bypass = native and policy.admin_bypass(principal, TODO_WRITE)
        all_shared = everything or bypass
        teams = await self._member_of(principal) if native and not all_shared else frozenset()
        boards = (
            frozenset(await self._entry_roles(principal)) if native and not all_shared else None
        )
        owner_id = await self.me(principal) if native else None
        permissions = (
            await self._board_permissions(principal, native=native, everything=everything)
            if not all_permissions and (native or everything)
            else frozenset[str]()
        )
        scope = ReadScope(
            all_shared=all_shared,
            team_ids=teams,
            owner_id=owner_id,
            permissions=permissions,
            all_permissions=all_permissions,
            board_ids=boards or frozenset(),
        )
        self._scopes[_cache_key(principal)] = scope
        return scope

    async def _board_permissions(
        self, principal: Principal, *, native: bool, everything: bool
    ) -> frozenset[str]:
        """The permissions of the permission boards that the principal reaches.

        Its own permissions by the native right, or the ones that its scope lets through
        by a global key.
        """
        permissions = (
            await self.session.scalars(
                select(TodoBoard.permission)
                .where(TodoBoard.kind == "permission", TodoBoard.permission.is_not(None))
                .distinct()
            )
        ).all()
        return frozenset(
            p
            for p in permissions
            if p and ((native and principal.has(p)) or (everything and principal.scope_allows(p)))
        )

    async def role(self, board: TodoBoard, principal: Principal) -> int:
        """Return the own role of the principal on the board (0: none; not ``todo.all``).

        The membership, the entries, the owner, the board permission or the admin
        bypass; all of them need ``todo.write`` in the token scope.
        """
        if not principal.scope_allows(TODO_WRITE):
            return 0
        match board.kind:
            case "personal":
                own = board.owner_id is not None and board.owner_id == await self.me(principal)
                return MANAGE if own else 0
            case "permission":
                return MANAGE if board.permission and principal.has(board.permission) else 0
            case _:
                if policy.admin_bypass(principal, TODO_WRITE):
                    return MANAGE
                entry = (await self._entry_roles(principal)).get(board.id, 0)
                if board.kind != "team" or board.team_id is None:
                    return entry
                if board.team_id in await self._manages(principal):
                    return MANAGE
                member = board.team_id in await self._member_of(principal)
                return max(entry, EDIT) if member else entry

    async def can_write(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal works on the cards of the board (``todo.all`` included)."""
        if principal.has(TODO_ALL) and global_reach(board, principal):
            return True
        return await self.role(board, principal) >= EDIT

    async def can_read(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal reads the board: a role, or a global key."""
        if reads_all(principal) and global_reach(board, principal):
            return True
        return await self.role(board, principal) >= READ

    async def can_configure(self, board: TodoBoard, principal: Principal) -> bool:
        """Tell if the principal edits the name, the columns, the labels and the entries.

        ``todo.all`` and ``todo.read_all`` never configure: the right is the role
        ``manage``, with ``todo.configure`` in the token scope.
        """
        if not principal.scope_allows(TODO_CONFIGURE):
            return False
        return await self.role(board, principal) >= MANAGE

    async def board_teams(self, board: TodoBoard) -> set[uuid.UUID]:
        """The own team of a team board and every team with an entry on the board."""
        if board.kind not in SHARED_KINDS:
            return set()
        own = {board.team_id} if board.team_id is not None else set()
        entries = await self.session.scalars(
            select(TodoBoardEntry.team_id).where(
                TodoBoardEntry.board_id == board.id, TodoBoardEntry.team_id.is_not(None)
            )
        )
        return own | {t for t in entries.all() if t is not None}

    async def gremium_of(self, board: TodoBoard) -> uuid.UUID | None:
        """The Gremium of the own team of a team board, when that team is inherent."""
        if board.team_id is None:
            return None
        return (await gremien_of_teams(self.session, (board.team_id,))).get(board.team_id)

    async def agenda_gremien(self, board: TodoBoard) -> set[uuid.UUID]:
        """The gremien whose meetings take a card of the board (specs 000326, 001069).

        The Gremium of every inherent team of the board: its own team and the teams of
        its entries, whatever their role. A free team, a personal and a permission board
        bring none.
        """
        teams = await self.board_teams(board)
        return set((await gremien_of_teams(self.session, teams)).values())

    async def members(self, board: TodoBoard) -> list[TodoMember]:
        """Return the people that the board accepts as assignees, by name."""
        rows = await self._member_rows(board)
        out = {
            pid: TodoMember(principal_id=pid, display_name=person_of(pid, name, email).display_name)
            for pid, name, email in rows
        }
        return sorted(
            out.values(), key=lambda m: ((m.display_name or "").casefold(), str(m.principal_id))
        )

    async def _member_rows(self, board: TodoBoard) -> Sequence[MemberRow]:
        """The id, name and e-mail of each member of the board; one person can repeat."""
        match board.kind:
            case "personal":
                return (
                    await self.session.execute(
                        select(
                            PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email
                        ).where(PrincipalRow.id == board.owner_id)
                    )
                ).all()
            case "permission":
                return await permission_holders(self.session, board.permission or "")
            case _:
                own = (board.team_id,) if board.team_id is not None else ()
                return await self._entry_member_rows(board.id, own)

    async def _entry_member_rows(
        self, board_id: uuid.UUID, own_teams: tuple[uuid.UUID, ...]
    ) -> Sequence[MemberRow]:
        """The persons with ``edit`` or ``manage``: own team members and entries."""
        editors = ("edit", "manage")
        entry_teams = (
            await self.session.scalars(
                select(TodoBoardEntry.team_id).where(
                    TodoBoardEntry.board_id == board_id,
                    TodoBoardEntry.team_id.is_not(None),
                    TodoBoardEntry.role.in_(editors),
                )
            )
        ).all()
        teams = {*own_teams, *(t for t in entry_teams if t is not None)}
        persons = select(TodoBoardEntry.principal_id).where(
            TodoBoardEntry.board_id == board_id,
            TodoBoardEntry.principal_id.is_not(None),
            TodoBoardEntry.role.in_(editors),
        )
        in_team = (PrincipalRow.id.in_(member_ids_stmt(teams)),) if teams else ()
        return (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email)
                .where(
                    or_(*in_team, PrincipalRow.id.in_(persons)),
                    PrincipalRow.active.is_(True),
                    PrincipalRow.merged_into.is_(None),
                )
                .distinct()
            )
        ).all()

    async def member_ids(self, board: TodoBoard) -> set[uuid.UUID]:
        """Return the ids of ``members``."""
        return {m.principal_id for m in await self.members(board)}
