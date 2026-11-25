"""Boards: list, read, create, change, entries (who may use a team board), archive, delete."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime

from sqlalchemy import func, select, update

from app.modules.auth import policy
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.people import DELETED_PERSON, person_refs
from app.modules.auth.principal import Principal
from app.modules.site_config.square_logos import logo_url_of, square_logo_variants
from app.modules.teams.members import TeamInfo, gremien_of_teams, team_infos
from app.modules.teams.models import Team
from app.modules.todos.access import TODO_CONFIGURE, can_create_board, token_reads
from app.modules.todos.boards import add_default_columns, ensure_personal_board
from app.modules.todos.grouping import grouped
from app.modules.todos.models import (
    TodoBoard,
    TodoBoardEntry,
    TodoCard,
    TodoColumn,
    TodoComment,
)
from app.modules.todos.schemas import (
    BoardCreate,
    BoardPatch,
    EntryIn,
    EntryOptionsOut,
    EntryPatch,
    EntryPersonOption,
    EntryTeamOption,
    TodoBoardEntryOut,
    TodoBoardOut,
    TodoBoardSummary,
    TodoCardTile,
    TodoMember,
)
from app.modules.todos.service.base import TodoServiceBase
from app.modules.todos.service.common import (
    _PICKER_PEOPLE,
    TodoMail,
    _board_order,
    _invalid,
    _new_entry,
    _now,
)
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError
from app.shared.paging import Page
from app.shared.search import escape_like


class BoardOps(TodoServiceBase):
    """Board reads and writes."""

    async def list_boards(
        self, principal: Principal, *, gremium_id: uuid.UUID | None = None
    ) -> list[TodoBoardSummary]:
        """List the readable boards: personal, the team boards by name, then the rest.

        ``gremium_id`` keeps the board of the inherent team of that Gremium.

        The first call of an account creates its personal board.

        Raises:
            ForbiddenError: A token whose scope allows none of ``todo.write``,
                ``todo.all`` and ``todo.read_all`` (HTTP 403).
        """
        if not token_reads(principal):
            raise ForbiddenError("The token scope does not allow to-dos.")
        me = await self.access.me(principal)
        if me is not None:
            await ensure_personal_board(self.session, me)
        scope = await self.access.scope(principal)
        of_gremium = (
            (TodoBoard.team_id.in_(select(Team.id).where(Team.gremium_id == gremium_id)),)
            if gremium_id is not None
            else ()
        )
        stmt = select(TodoBoard).where(
            scope.condition(), TodoBoard.archived_at.is_(None), *of_gremium
        )
        found = (await self.session.scalars(stmt)).all()
        if not found:
            return []
        counts = {
            board_id: int(n)
            for board_id, n in (
                await self.session.execute(
                    select(TodoCard.board_id, func.count())
                    .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                    .where(
                        TodoCard.board_id.in_([b.id for b in found]),
                        TodoCard.archived_at.is_(None),
                        TodoColumn.is_done.is_(False),
                    )
                    .group_by(TodoCard.board_id)
                )
            ).all()
        }
        boards = sorted(found, key=_board_order)
        entry_teams = grouped(
            (
                await self.session.execute(
                    select(TodoBoardEntry.board_id, TodoBoardEntry.team_id).where(
                        TodoBoardEntry.board_id.in_([b.id for b in found]),
                        TodoBoardEntry.team_id.is_not(None),
                    )
                )
            )
            .tuples()
            .all()
        )
        teams = {
            *(b.team_id for b in found if b.team_id is not None),
            *(t for ts in entry_teams.values() for t in ts if t is not None),
        }
        gremium_of = await gremien_of_teams(self.session, teams)
        return [
            TodoBoardSummary(
                id=b.id,
                name=b.name,
                kind=b.kind,  # pyright: ignore[reportArgumentType]
                team_id=b.team_id,
                gremium_id=gremium_of.get(b.team_id) if b.team_id is not None else None,
                can_write=await self.access.can_write(b, principal),
                can_configure=await self.access.can_configure(b, principal),
                open_count=counts.get(b.id, 0),
                agenda_gremium_ids=_agenda_ids(b, entry_teams.get(b.id, ()), gremium_of),
            )
            for b in boards
        ]

    async def board(self, board_id: uuid.UUID, principal: Principal) -> TodoBoardOut:
        """Return a board with its columns, labels and the tiles of the live cards.

        Raises:
            NotFoundError: The board is unknown or not readable (HTTP 404).
        """
        board = await self._board(board_id, principal)
        return await self._board_out(board, principal)

    async def patch_board(
        self, board_id: uuid.UUID, payload: BoardPatch, principal: Principal
    ) -> TodoBoardOut:
        """Rename the board or change ``archiveAfterDays`` (``null`` = never)."""
        board = await self._configurable(board_id, principal)
        fields = payload.model_fields_set
        if payload.name is not None:
            board.name = payload.name.strip() or board.name
        if "archive_after_days" in fields:
            board.archive_after_days = payload.archive_after_days
        self._touch(board)
        await self.session.commit()
        return await self._board_out(board, principal)

    async def members(self, board_id: uuid.UUID, principal: Principal) -> list[TodoMember]:
        """Return the assignable people of a readable board."""
        board = await self._board(board_id, principal)
        return await self.access.members(board)

    async def create_board(self, payload: BoardCreate, principal: Principal) -> TodoBoardOut:
        """Create a free board with the default columns (spec 001061).

        The creator becomes a member with ``manage``. A person entry of the payload gets
        the mail ``todo_board_added`` (spec 001071), the creator none.

        Raises:
            ForbiddenError: Neither an admin nor ``todo.create_board`` (403
                ``board_create_required``).
            ValidationProblem: An unknown, double or empty entry (422).
        """
        if not can_create_board(principal):
            raise ForbiddenError(
                "Creating a board needs todo.create_board.", code="board_create_required"
            )
        actor = await self._actor(principal)
        targets = [await self._entry_target(entry) for entry in payload.entries]
        if len(set(targets)) != len(targets):
            raise _invalid("An entry is in the list twice.", "entry_duplicate", "entries")
        board = TodoBoard(id=uuid.uuid4(), name=payload.name.strip() or payload.name, kind="free")
        self.session.add(board)
        await self.session.flush()
        add_default_columns(self.session, board.id)
        roles = {
            **{target: entry.role for target, entry in zip(targets, payload.entries, strict=True)},
            ("person", actor): "manage",
        }
        for (kind, target_id), role in roles.items():
            self.session.add(_new_entry(board.id, kind, target_id, role))
            if kind == "person" and target_id != actor:
                self._board_mail(board, target_id, role, actor)
        await self.session.flush()
        return await self._board_out(board, principal)

    async def _entry_target(self, entry: EntryIn) -> tuple[str, uuid.UUID]:
        """Check the target of an entry: exactly one known team or active person."""
        if (entry.team_id is None) == (entry.principal_id is None):
            raise _invalid(
                "An entry names exactly one team or one person.", "entry_target", "entries"
            )
        if entry.team_id is not None:
            if await self.session.get(Team, entry.team_id) is None:
                raise _invalid("Unknown team.", "entry_target_not_found", "teamId")
            return ("team", entry.team_id)
        person = await self.session.get(PrincipalRow, entry.principal_id)
        if person is None or not person.active or person.merged_into is not None:
            raise _invalid("Unknown person.", "entry_target_not_found", "principalId")
        return ("person", person.id)

    def _board_mail(
        self, board: TodoBoard, recipient: uuid.UUID, role: str, actor: uuid.UUID
    ) -> None:
        if recipient != actor:
            self.outbox.append(
                TodoMail("board_added", None, (recipient,), actor, board_id=board.id, role=role)
            )

    async def entries(self, board_id: uuid.UUID, principal: Principal) -> list[TodoBoardEntryOut]:
        """The member entries of a readable board: the own team first, then by name."""
        board = await self._board(board_id, principal)
        return await self._entry_outs(board)

    async def _entry_outs(self, board: TodoBoard) -> list[TodoBoardEntryOut]:
        rows = (
            await self.session.scalars(
                select(TodoBoardEntry).where(TodoBoardEntry.board_id == board.id)
            )
        ).all()
        team_ids = {r.team_id for r in rows if r.team_id is not None} | (
            {board.team_id} if board.team_id is not None else set()
        )
        teams = {t.id: t for t in await team_infos(self.session, ids=team_ids)}
        logos = await square_logo_variants(self.session, (t.cd_variant_id for t in teams.values()))
        people = await person_refs(self.session, (r.principal_id for r in rows))
        own = (
            [_team_entry(None, teams[board.team_id], "edit", logos, fixed=True)]
            if board.kind == "team" and board.team_id is not None and board.team_id in teams
            else []
        )
        outs = [
            _team_entry(r.id, teams[r.team_id], r.role, logos)
            if r.team_id is not None and r.team_id in teams
            else TodoBoardEntryOut(
                id=r.id,
                kind="person",
                target_id=r.principal_id,  # pyright: ignore[reportArgumentType]
                name=(people.get(r.principal_id) or DELETED_PERSON).display_name or "",  # pyright: ignore[reportArgumentType]
                role=r.role,  # pyright: ignore[reportArgumentType]
            )
            for r in rows
        ]
        return own + sorted(
            outs, key=lambda e: (e.kind != "team", e.name.casefold(), str(e.target_id))
        )

    async def entry_options(self, principal: Principal, q: str) -> EntryOptionsOut:
        """The hits of the shared picker of teams and persons (spec 003071).

        Every team whose name holds ``q`` (all for an empty ``q``) with its parent and
        the logo of its Gremium, and the active persons whose name holds ``q``, from two
        characters on and at most ten, by name only. A scoped OAuth token finds nothing:
        the picker is a page of the app, the MCP tools name the ids.
        """
        if principal.scope_permissions is not None:
            return EntryOptionsOut(teams=[], persons=[])
        term = q.strip()
        pattern = f"%{escape_like(term)}%"
        teams = await team_infos(self.session, pattern=pattern if term else None)
        logos = await square_logo_variants(self.session, (t.cd_variant_id for t in teams))
        persons = (
            (
                await self.session.execute(
                    select(PrincipalRow.id, PrincipalRow.display_name)
                    .where(
                        PrincipalRow.active.is_(True),
                        PrincipalRow.merged_into.is_(None),
                        PrincipalRow.display_name.ilike(pattern, escape="\\"),
                    )
                    .order_by(PrincipalRow.display_name, PrincipalRow.id)
                    .limit(_PICKER_PEOPLE)
                )
            )
            .tuples()
            .all()
            if len(term) >= 2
            else []
        )
        return EntryOptionsOut(
            teams=[
                EntryTeamOption(
                    id=t.id,
                    name=t.name,
                    gremium_id=t.gremium_id,
                    parent_name=t.parent_name,
                    logo_url=_logo(t.gremium_id, t.cd_variant_id, logos),
                )
                for t in teams
            ],
            persons=[EntryPersonOption(id=pid, name=name or "") for pid, name in persons],
        )

    def _supports_entries(self, board: TodoBoard) -> None:
        if board.kind not in ("team", "free"):
            raise _invalid(
                "Only a team board or a free board has entries.",
                "entries_not_supported",
                "boardId",
            )

    async def add_entry(
        self, board_id: uuid.UUID, payload: EntryIn, principal: Principal
    ) -> list[TodoBoardEntryOut]:
        """Add a team or a person to a board (specs 001064, 001077, 003068).

        Raises:
            ConflictError: The target is on the board already (409 ``entry_exists``) or
                is the own team of the board (409 ``own_team_entry``).
        """
        board = await self._configurable(board_id, principal)
        self._supports_entries(board)
        actor = await self._actor(principal)
        await self._lock_board(board.id)
        kind, target_id = await self._entry_target(payload)
        if kind == "team" and target_id == board.team_id:
            raise ConflictError(
                "The own team is a fixed member of its board.", code="own_team_entry"
            )
        column = TodoBoardEntry.team_id if kind == "team" else TodoBoardEntry.principal_id
        present = await self.session.scalar(
            select(TodoBoardEntry.id).where(
                TodoBoardEntry.board_id == board.id, column == target_id
            )
        )
        if present is not None:
            raise ConflictError("The entry exists.", code="entry_exists")
        self.session.add(_new_entry(board.id, kind, target_id, payload.role))
        if kind == "person":
            self._board_mail(board, target_id, payload.role, actor)
        self._touch(board)
        await self.session.flush()
        return await self._entry_outs(board)

    async def _entry(self, board: TodoBoard, entry_id: uuid.UUID) -> TodoBoardEntry:
        entry = await self.session.get(TodoBoardEntry, entry_id)
        if entry is None or entry.board_id != board.id:
            raise NotFoundError(f"entry {entry_id} not found")
        return entry

    async def _keep_a_manager(self, board: TodoBoard, entry: TodoBoardEntry) -> None:
        """Refuse to drop the last ``manage`` entry of a free board (409 ``last_manager``)."""
        if board.kind != "free" or entry.role != "manage":
            return
        others = await self.session.scalar(
            select(func.count())
            .select_from(TodoBoardEntry)
            .where(
                TodoBoardEntry.board_id == board.id,
                TodoBoardEntry.role == "manage",
                TodoBoardEntry.id != entry.id,
            )
        )
        if not others:
            raise ConflictError(
                "The board needs at least one entry with the role manage.", code="last_manager"
            )

    async def patch_entry(
        self, board_id: uuid.UUID, entry_id: uuid.UUID, payload: EntryPatch, principal: Principal
    ) -> list[TodoBoardEntryOut]:
        """Change the role of an entry; the last manager stays (409 ``last_manager``)."""
        board = await self._configurable(board_id, principal)
        await self._lock_board(board.id)
        entry = await self._entry(board, entry_id)
        if payload.role != "manage":
            await self._keep_a_manager(board, entry)
        await self.session.execute(
            update(TodoBoardEntry).where(TodoBoardEntry.id == entry.id).values(role=payload.role)
        )
        self._touch(board)
        await self.session.flush()
        return await self._entry_outs(board)

    async def delete_entry(
        self, board_id: uuid.UUID, entry_id: uuid.UUID, principal: Principal
    ) -> list[TodoBoardEntryOut]:
        """Remove an entry; the last manager stays (409 ``last_manager``)."""
        board = await self._configurable(board_id, principal)
        await self._lock_board(board.id)
        entry = await self._entry(board, entry_id)
        await self._keep_a_manager(board, entry)
        await self.session.delete(entry)
        self._touch(board)
        await self.session.flush()
        return await self._entry_outs(board)

    def _free(self, board: TodoBoard) -> None:
        if board.kind != "free":
            raise _invalid("Only a free board is archived or deleted.", "board_not_free", "boardId")

    async def archive_board(self, board_id: uuid.UUID, principal: Principal) -> TodoBoardSummary:
        """Archive a free board: hidden and read-only (spec 001068)."""
        board = await self._configurable(board_id, principal, archived=True)
        self._free(board)
        if board.archived_at is None:
            await self._set_archived(board, _now())
            await self.session.flush()
        return await self._summary(board, principal)

    async def restore_board(self, board_id: uuid.UUID, principal: Principal) -> TodoBoardSummary:
        """Restore an archived free board (spec 001068)."""
        board = await self._configurable(board_id, principal, archived=True)
        self._free(board)
        if board.archived_at is not None:
            await self._set_archived(board, None)
            await self.session.flush()
        return await self._summary(board, principal)

    async def _set_archived(self, board: TodoBoard, when: datetime | None) -> None:
        """Set or clear ``archived_at`` (the identity map follows the update)."""
        await self.session.execute(
            update(TodoBoard).where(TodoBoard.id == board.id).values(archived_at=when)
        )
        self._touch(board)

    async def archived_boards(self, principal: Principal) -> list[TodoBoardSummary]:
        """The archived free boards that the principal manages, by name."""
        if not token_reads(principal):
            raise ForbiddenError("The token scope does not allow to-dos.")
        found = (
            await self.session.scalars(
                select(TodoBoard).where(
                    TodoBoard.kind == "free", TodoBoard.archived_at.is_not(None)
                )
            )
        ).all()
        return [
            await self._summary(b, principal)
            for b in sorted(found, key=_board_order)
            if await self.access.can_configure(b, principal)
        ]

    async def _summary(self, board: TodoBoard, principal: Principal) -> TodoBoardSummary:
        return TodoBoardSummary(
            id=board.id,
            name=board.name,
            kind=board.kind,  # pyright: ignore[reportArgumentType]
            team_id=board.team_id,
            gremium_id=await self.access.gremium_of(board),
            can_write=await self.access.can_write(board, principal),
            can_configure=await self.access.can_configure(board, principal),
            archived=board.archived_at is not None,
        )

    async def delete_board(self, board_id: uuid.UUID, principal: Principal) -> list[str]:
        """Delete an archived free board with its cards; admins only (spec 001068).

        The board goes first and then the cards, the order of every to-do write, and the
        comment files lose their rows like at a gremium delete. The caller commits and then
        removes the objects of the returned storage keys, so a failed commit keeps them.

        Raises:
            ForbiddenError: Not an admin (403 ``board_delete_admin_only``).
            ConflictError: The board is not archived (409 ``board_not_archived``).
        """
        board = await self._board(board_id, principal)
        if not policy.admin_bypass(principal, TODO_CONFIGURE):
            raise ForbiddenError("Only an admin deletes a board.", code="board_delete_admin_only")
        self._free(board)
        if board.archived_at is None:
            raise ConflictError("Archive the board first.", code="board_not_archived")
        await self._lock_board(board.id)
        await self.session.execute(
            select(TodoCard.id)
            .where(TodoCard.board_id == board.id)
            .order_by(TodoCard.id)
            .with_for_update()
        )
        comment_ids = list(
            (
                await self.session.scalars(
                    select(TodoComment.id)
                    .join(TodoCard, TodoCard.id == TodoComment.card_id)
                    .where(TodoCard.board_id == board.id)
                    .order_by(TodoComment.id)
                )
            ).all()
        )
        await self.files.lock_for_messages("todo_comment", comment_ids)
        storage_keys = await self.files.drop_for_messages(
            "todo_comment", comment_ids, actor=principal.sub
        )
        await self.session.delete(board)
        self._touch(board)
        await self.session.flush()
        return storage_keys

    async def archive(
        self,
        board_id: uuid.UUID,
        principal: Principal,
        *,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[TodoCardTile]:
        """Page through the archived cards of a board, newest archive first."""
        board = await self._board(board_id, principal)
        term = (q or "").strip()
        titled = (TodoCard.title.ilike(f"%{escape_like(term)}%", escape="\\"),) if term else ()
        conds = (
            TodoCard.board_id == board.id,
            TodoCard.archived_at.is_not(None),
            *titled,
        )
        total = await self.session.scalar(select(func.count()).select_from(TodoCard).where(*conds))
        cards = list(
            (
                await self.session.scalars(
                    select(TodoCard)
                    .where(*conds)
                    .order_by(TodoCard.archived_at.desc(), TodoCard.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        return Page[TodoCardTile](
            items=await self.tiles(cards, principal),
            total=int(total or 0),
            limit=limit,
            offset=offset,
        )


def _logo(
    gremium_id: uuid.UUID | None, variant: uuid.UUID | None, logos: frozenset[uuid.UUID]
) -> str | None:
    """The square logo of the Gremium of an inherent team, else None."""
    return logo_url_of(gremium_id, variant, logos) if gremium_id is not None else None


def _team_entry(
    entry_id: uuid.UUID | None,
    team: TeamInfo,
    role: str,
    logos: frozenset[uuid.UUID],
    *,
    fixed: bool = False,
) -> TodoBoardEntryOut:
    """The entry of a team: its shown name, its Gremium and the logo of the Gremium."""
    return TodoBoardEntryOut(
        id=entry_id,
        kind="team",
        target_id=team.id,
        name=team.name,
        role=role,  # pyright: ignore[reportArgumentType]
        fixed=fixed,
        gremium_id=team.gremium_id,
        logo_url=_logo(team.gremium_id, team.cd_variant_id, logos),
    )


def _agenda_ids(
    board: TodoBoard,
    entries: Iterable[uuid.UUID | None],
    gremium_of: Mapping[uuid.UUID, uuid.UUID],
) -> tuple[uuid.UUID, ...]:
    """The Gremien of the own team and of the entry teams of a team or free board, sorted."""
    if board.kind not in ("team", "free"):
        return ()
    teams = {board.team_id, *entries}
    return tuple(
        sorted({gremium_of[t] for t in teams if t is not None and t in gremium_of}, key=str)
    )
