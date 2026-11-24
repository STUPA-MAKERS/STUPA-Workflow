"""Boards: list, read, create, change, entries (who may use a team board), archive, delete."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, true, update

from app.modules.auth import policy
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.people import DELETED_PERSON, person_refs
from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium
from app.modules.site_config.square_logos import logo_url_of, square_logo_variants
from app.modules.todos.access import TODO_CONFIGURE, can_create_board, token_reads
from app.modules.todos.boards import add_default_columns, ensure_personal_board
from app.modules.todos.grouping import grouped
from app.modules.todos.models import (
    TodoBoard,
    TodoBoardEntry,
    TodoCard,
    TodoCardEvent,
    TodoColumn,
    TodoComment,
)
from app.modules.todos.schemas import (
    BoardCreate,
    BoardPatch,
    EntryGremiumOption,
    EntryIn,
    EntryOptionsOut,
    EntryPatch,
    EntryPersonOption,
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
    _agenda_ids,
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
        """List the readable boards: personal, the gremium boards by name, then team.

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
        of_gremium = (TodoBoard.gremium_id == gremium_id,) if gremium_id is not None else ()
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
        entry_gremien = grouped(
            (
                await self.session.execute(
                    select(TodoBoardEntry.board_id, TodoBoardEntry.gremium_id).where(
                        TodoBoardEntry.board_id.in_([b.id for b in found]),
                        TodoBoardEntry.gremium_id.is_not(None),
                    )
                )
            )
            .tuples()
            .all()
        )
        return [
            TodoBoardSummary(
                id=b.id,
                name=b.name,
                kind=b.kind,  # pyright: ignore[reportArgumentType]
                gremium_id=b.gremium_id,
                can_write=await self.access.can_write(b, principal),
                can_configure=await self.access.can_configure(b, principal),
                open_count=counts.get(b.id, 0),
                agenda_gremium_ids=_agenda_ids(b, entry_gremien.get(b.id, ())),
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
        """Check the target of an entry: exactly one known gremium or active person."""
        if (entry.gremium_id is None) == (entry.principal_id is None):
            raise _invalid(
                "An entry names exactly one gremium or one person.", "entry_target", "entries"
            )
        if entry.gremium_id is not None:
            if await self.session.get(Gremium, entry.gremium_id) is None:
                raise _invalid("Unknown gremium.", "entry_target_not_found", "gremiumId")
            return ("gremium", entry.gremium_id)
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
        """The member entries of a readable board: the own gremium first, then by name."""
        board = await self._board(board_id, principal)
        return await self._entry_outs(board)

    async def _entry_outs(self, board: TodoBoard) -> list[TodoBoardEntryOut]:
        rows = (
            await self.session.scalars(
                select(TodoBoardEntry).where(TodoBoardEntry.board_id == board.id)
            )
        ).all()
        gremium_ids = {r.gremium_id for r in rows if r.gremium_id is not None} | (
            {board.gremium_id} if board.gremium_id is not None else set()
        )
        gremien = (
            {
                gid: (name, variant)
                for gid, name, variant in (
                    await self.session.execute(
                        select(Gremium.id, Gremium.name, Gremium.cd_variant_id).where(
                            Gremium.id.in_(gremium_ids)
                        )
                    )
                ).tuples()
            }
            if gremium_ids
            else {}
        )
        names = {gid: name for gid, (name, _variant) in gremien.items()}
        logos = await square_logo_variants(self.session, (v for _n, v in gremien.values()))
        logo = {gid: logo_url_of(gid, v, logos) for gid, (_n, v) in gremien.items()}
        people = await person_refs(self.session, (r.principal_id for r in rows))
        own = (
            [
                TodoBoardEntryOut(
                    kind="gremium",
                    target_id=board.gremium_id,
                    name=names.get(board.gremium_id, ""),
                    role="edit",
                    fixed=True,
                    logo_url=logo.get(board.gremium_id),
                )
            ]
            if board.kind == "gremium" and board.gremium_id is not None
            else []
        )
        outs = [
            TodoBoardEntryOut(
                id=r.id,
                kind="gremium" if r.gremium_id is not None else "person",
                target_id=r.gremium_id or r.principal_id,  # pyright: ignore[reportArgumentType]
                name=(
                    names.get(r.gremium_id, "")
                    if r.gremium_id is not None
                    else (people.get(r.principal_id) or DELETED_PERSON).display_name or ""  # pyright: ignore[reportArgumentType]
                ),
                role=r.role,  # pyright: ignore[reportArgumentType]
                logo_url=logo.get(r.gremium_id) if r.gremium_id is not None else None,
            )
            for r in rows
        ]
        return own + sorted(
            outs, key=lambda e: (e.kind != "gremium", e.name.casefold(), str(e.target_id))
        )

    async def entry_options(self, principal: Principal, q: str) -> EntryOptionsOut:
        """The hits of the shared picker of gremien and persons (spec 001074).

        Every gremium whose name holds ``q`` (all for an empty ``q``) with its logo
        path, and the active persons whose name holds ``q``, from two characters on and
        at most ten, by name only. A scoped OAuth token finds nothing: the picker is a
        page of the app, the MCP tools name the ids.
        """
        if principal.scope_permissions is not None:
            return EntryOptionsOut(gremien=[], persons=[])
        term = q.strip()
        pattern = f"%{escape_like(term)}%"
        gremien = (
            (
                await self.session.execute(
                    select(Gremium.id, Gremium.name, Gremium.cd_variant_id)
                    .where(Gremium.name.ilike(pattern, escape="\\") if term else true())
                    .order_by(Gremium.name, Gremium.id)
                )
            )
            .tuples()
            .all()
        )
        logos = await square_logo_variants(self.session, (v for _g, _n, v in gremien))
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
            gremien=[
                EntryGremiumOption(id=gid, name=name, logo_url=logo_url_of(gid, v, logos))
                for gid, name, v in gremien
            ],
            persons=[EntryPersonOption(id=pid, name=name or "") for pid, name in persons],
        )

    def _supports_entries(self, board: TodoBoard) -> None:
        if board.kind not in ("gremium", "free"):
            raise _invalid(
                "Only a gremium board or a free board has entries.",
                "entries_not_supported",
                "boardId",
            )

    async def add_entry(
        self, board_id: uuid.UUID, payload: EntryIn, principal: Principal
    ) -> list[TodoBoardEntryOut]:
        """Add a gremium or a person to a board (specs 001064, 001077).

        Raises:
            ConflictError: The target is on the board already (409 ``entry_exists``) or
                is the own gremium of the board (409 ``own_gremium_entry``).
        """
        board = await self._configurable(board_id, principal)
        self._supports_entries(board)
        actor = await self._actor(principal)
        await self._lock_board(board.id)
        kind, target_id = await self._entry_target(payload)
        if kind == "gremium" and target_id == board.gremium_id:
            raise ConflictError(
                "The own gremium is a fixed member of its board.", code="own_gremium_entry"
            )
        column = TodoBoardEntry.gremium_id if kind == "gremium" else TodoBoardEntry.principal_id
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
            gremium_id=board.gremium_id,
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
        events_only: bool = False,
    ) -> Page[TodoCardTile]:
        """Page through the archived cards of a board, newest archive first.

        ``events_only`` keeps the Events: the filter ``Veranstaltungen mit Archiv``.
        """
        board = await self._board(board_id, principal)
        term = (q or "").strip()
        events = (TodoCard.id.in_(select(TodoCardEvent.card_id)),) if events_only else ()
        titled = (TodoCard.title.ilike(f"%{escape_like(term)}%", escape="\\"),) if term else ()
        conds = (
            TodoCard.board_id == board.id,
            TodoCard.archived_at.is_not(None),
            *events,
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
