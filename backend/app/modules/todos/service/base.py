"""Shared base of the to-do service ops classes: access, locks, lookups, events, pings, mails."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Sequence

from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.people import person_refs
from app.modules.auth.principal import Principal
from app.modules.files.service import FilesService
from app.modules.tickets.models import TicketEvent
from app.modules.todos import events as todo_events
from app.modules.todos import link_store
from app.modules.todos.access import BoardAccess, token_reads
from app.modules.todos.grouping import grouped
from app.modules.todos.link_store import Edge
from app.modules.todos.links import HIDDEN, LinkRef, LinkResolver, Resolved, link_kinds_on
from app.modules.todos.live import BoardPings
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoCardLabel,
    TodoCheckItem,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoEventSeries,
    TodoLabel,
)
from app.modules.todos.schemas import EventIn, TodoBoardOut, TodoCardTile
from app.modules.todos.service.common import (
    CardLink,
    MailKind,
    TodoMail,
    _Facts,
    _in_column_order,
    _invalid,
    _not_archived,
    _now,
    card_links,
)
from app.modules.todos.service.ranks import _card_moved
from app.modules.todos.service.rows import _column_outs, _label_out, _tile
from app.shared.errors import ForbiddenError, NotFoundError


class TodoServiceBase:
    """Constructor and helpers that every ops class of ``TodoService`` uses."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        access: BoardAccess | None = None,
        links: LinkResolver | None = None,
        files: FilesService | None = None,
    ) -> None:
        """Bind the service to a session and its access, link and file helpers."""
        self.session = session
        self.files = files or FilesService(session)
        self.access = access or BoardAccess(session)
        self.links = links or LinkResolver(session, self.access)
        self.outbox: list[TodoMail] = []
        #: The boards and cards of this request, published after the commit (``live``).
        self.pings = BoardPings()

    async def _actor(self, principal: Principal) -> uuid.UUID:
        me = await self.access.me(principal)
        if me is None:
            raise NotFoundError("account not found")
        return me

    async def actor_of(self, principal: Principal) -> uuid.UUID:
        """The principal row id of the caller (the author of a link)."""
        return await self._actor(principal)

    async def _board(
        self, board_id: uuid.UUID, principal: Principal, *, write: bool = False
    ) -> TodoBoard:
        """Load a readable board; ``write`` also needs the write right (else 403)."""
        board = await self.session.get(TodoBoard, board_id)
        if board is None or not await self.access.can_read(board, principal):
            raise NotFoundError(f"board {board_id} not found")
        if write:
            await self._writable(board, principal)
        return board

    async def _writable(self, board: TodoBoard, principal: Principal) -> None:
        """Raise 403 ``todo_write_required`` for a readable board that is not writable.

        An archived board is read-only: 409 ``board_archived`` (spec 001068).
        """
        _not_archived(board)
        if not await self.access.can_write(board, principal):
            raise ForbiddenError(
                "Changing the cards of this board needs todo.write.",
                code="todo_write_required",
            )

    async def _configurable(
        self, board_id: uuid.UUID, principal: Principal, *, archived: bool = False
    ) -> TodoBoard:
        """Load a board that the principal configures (403 ``todo_configure_required``).

        An archived board is read-only (409 ``board_archived``) unless ``archived``.
        """
        board = await self._board(board_id, principal)
        if not archived:
            _not_archived(board)
        if not await self.access.can_configure(board, principal):
            raise ForbiddenError(
                "Changing this board needs todo.configure.", code="todo_configure_required"
            )
        return board

    async def _card(
        self,
        card_id: uuid.UUID,
        principal: Principal,
        *,
        lock: bool = False,
        write: bool = False,
    ) -> tuple[TodoCard, TodoBoard]:
        """Load a card and its board; ``lock`` locks the board first, then the card.

        An unreadable board is 404; ``write`` also needs the write right of the board
        (403 ``todo_write_required``). A card that a parallel transfer moved to
        another board while ``lock`` waited is 409 ``card_moved``, because the lock
        held is the lock of the old board.

        Every card write passes ``lock`` (the moves and the transfer lock the board
        themselves), so a write that a transfer overtakes is ``card_moved`` and its
        ping goes to the board that the card is on. Every write locks the board
        before a card, because a move locks the board and then updates the card, and
        the other order deadlocks with it.

        The card lock is ``FOR NO KEY UPDATE``, because no write changes the key of a
        card, and ``FOR UPDATE`` conflicts with the ``FOR KEY SHARE`` lock of a foreign
        key check. Two cards on two boards that link each other at the same time
        would deadlock: each holds its own card and its link insert waits for the
        other card.

        ``populate_existing`` refreshes the same object, so the board id of a known card
        is kept before the reload.
        """
        if lock:
            known = await self.session.get(TodoCard, card_id)
            if known is None:
                raise NotFoundError(f"card {card_id} not found")
            locked_board = known.board_id
            await self._lock_board(locked_board)
            card = await self.session.scalar(
                select(TodoCard)
                .where(TodoCard.id == card_id)
                .with_for_update(key_share=True)
                .execution_options(populate_existing=True)
            )
            if card is not None and card.board_id != locked_board:
                raise _card_moved()
        else:
            card = await self.session.get(TodoCard, card_id)
        if card is None:
            raise NotFoundError(f"card {card_id} not found")
        board = await self.session.get(TodoBoard, card.board_id)
        if board is None or not await self.access.can_read(board, principal):
            raise NotFoundError(f"card {card_id} not found")
        if write:
            await self._writable(board, principal)
        return card, board

    async def _lock_board(self, board_id: uuid.UUID) -> None:
        await self.session.execute(
            select(TodoBoard.id).where(TodoBoard.id == board_id).with_for_update()
        )

    def _touch(
        self, board: TodoBoard, card: TodoCard | None = None, *, removed: bool = False
    ) -> None:
        """Bump the board (its ETag changes) and record the ping of the write.

        Without ``card`` the write changed the board itself; ``removed`` says the card
        left the board (archived or transferred away).
        """
        board.updated_at = _now()
        self.pings.touch(board.id, card.id if card is not None else None, removed=removed)

    def _event(
        self,
        card: TodoCard,
        kind: str,
        actor: uuid.UUID | None,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        """Add an event of a card, stamped with the clock of the process.

        One request can write several events, and the timeline orders them by this time.
        """
        self.session.add(
            TodoEvent(
                id=uuid.uuid4(),
                card_id=card.id,
                actor_id=actor,
                kind=kind,
                payload=payload or {},
                created_at=_now(),
            )
        )

    async def _columns(self, board_id: uuid.UUID) -> list[TodoColumn]:
        return list(
            (
                await self.session.scalars(
                    select(TodoColumn)
                    .where(TodoColumn.board_id == board_id)
                    .order_by(TodoColumn.position, TodoColumn.id)
                )
            ).all()
        )

    async def _labels(self, board_id: uuid.UUID) -> list[TodoLabel]:
        return list(
            (
                await self.session.scalars(
                    select(TodoLabel)
                    .where(TodoLabel.board_id == board_id)
                    .order_by(func.lower(TodoLabel.name), TodoLabel.id)
                )
            ).all()
        )

    async def _column_cards(
        self, column_id: uuid.UUID, *, exclude: uuid.UUID | None = None
    ) -> list[TodoCard]:
        others = (TodoCard.id != exclude,) if exclude is not None else ()
        stmt = select(TodoCard).where(
            TodoCard.column_id == column_id, TodoCard.archived_at.is_(None), *others
        )
        return list((await self.session.scalars(stmt.order_by(TodoCard.rank, TodoCard.id))).all())

    async def _all_column_cards(self, column_id: uuid.UUID) -> list[TodoCard]:
        """Return every card of a column, the archived ones too, in rank order."""
        return list(
            (
                await self.session.scalars(
                    select(TodoCard)
                    .where(TodoCard.column_id == column_id)
                    .order_by(TodoCard.rank, TodoCard.id)
                )
            ).all()
        )

    async def _facts(self, cards: Sequence[TodoCard], principal: Principal) -> _Facts:
        if not cards:
            return _Facts()
        ids = [c.id for c in cards]
        label_rows = (
            await self.session.execute(
                select(TodoCardLabel.card_id, TodoCardLabel.label_id).where(
                    TodoCardLabel.card_id.in_(ids)
                )
            )
        ).all()
        assignee_rows = (
            await self.session.execute(
                select(TodoAssignee.card_id, TodoAssignee.principal_id).where(
                    TodoAssignee.card_id.in_(ids)
                )
            )
        ).all()
        checklist_rows = (
            await self.session.execute(
                select(
                    TodoCheckItem.card_id,
                    func.count(),
                    func.count().filter(TodoCheckItem.done.is_(True)),
                )
                .where(TodoCheckItem.card_id.in_(ids))
                .group_by(TodoCheckItem.card_id)
            )
        ).all()
        comment_rows = (
            await self.session.execute(
                select(TodoComment.card_id, func.count())
                .where(TodoComment.card_id.in_(ids), TodoComment.deleted_at.is_(None))
                .group_by(TodoComment.card_id)
            )
        ).all()
        link_rows = await link_store.edges(
            self.session, "todo", ids, await link_kinds_on(self.session)
        )
        assignees = grouped((card_id, principal_id) for card_id, principal_id in assignee_rows)
        people = await person_refs(
            self.session, {pid for pids in assignees.values() for pid in pids}
        )
        links, resolved = await self._card_links(set(ids), link_rows, principal)
        events = await todo_events.event_rows(self.session, ids)
        series = await todo_events.series_names(
            self.session, (row.series_id for row in events.values())
        )
        return _Facts(
            labels=grouped((card_id, label_id) for card_id, label_id in label_rows),
            assignees=assignees,
            checklist={card_id: (int(done), int(total)) for card_id, total, done in checklist_rows},
            comments={card_id: int(count) for card_id, count in comment_rows},
            links=links,
            people=people,
            resolved=resolved,
            events=events,
            series=series,
        )

    async def _card_links(
        self, ids: set[uuid.UUID], rows: Sequence[Edge], principal: Principal
    ) -> tuple[dict[uuid.UUID, tuple[CardLink, ...]], dict[LinkRef, Resolved]]:
        """The links of the cards ``ids`` and the resolved first link of each card.

        A linked card shows only when the principal reads it (spec 000573).
        """
        firsts = {edge.own_id: edge.target for edge in reversed(rows)}
        resolved = await self.links.resolve(
            {*firsts.values(), *(edge.target for edge in rows if edge.kind == "todo")}, principal
        )
        readable = [
            edge
            for edge in rows
            if edge.kind != "todo" or resolved.get(edge.target, HIDDEN).accessible
        ]
        return card_links(readable), resolved

    async def tiles(self, cards: Sequence[TodoCard], principal: Principal) -> list[TodoCardTile]:
        """Build the tiles of the cards (in the given order)."""
        facts = await self._facts(cards, principal)
        return [_tile(c, facts) for c in cards]

    async def _board_out(self, board: TodoBoard, principal: Principal) -> TodoBoardOut:
        columns = await self._columns(board.id)
        labels = await self._labels(board.id)
        live = (
            await self.session.scalars(
                select(TodoCard)
                .where(TodoCard.board_id == board.id, TodoCard.archived_at.is_(None))
                .order_by(TodoCard.rank, TodoCard.id)
            )
        ).all()
        archived = await self.session.scalar(
            select(func.count())
            .select_from(TodoCard)
            .where(TodoCard.board_id == board.id, TodoCard.archived_at.is_not(None))
        )
        cards = _in_column_order(live, columns)
        per_column = Counter(card.column_id for card in cards)
        return TodoBoardOut(
            id=board.id,
            name=board.name,
            kind=board.kind,  # pyright: ignore[reportArgumentType]
            gremium_id=board.gremium_id,
            archive_after_days=board.archive_after_days,
            can_write=await self.access.can_write(board, principal),
            can_configure=await self.access.can_configure(board, principal),
            columns=_column_outs(columns, per_column),
            labels=tuple(_label_out(label) for label in labels),
            cards=await self.tiles(cards, principal),
            archived_count=int(archived or 0),
            archived=board.archived_at is not None,
            agenda_gremium_ids=tuple(sorted(await self.access.agenda_gremien(board), key=str)),
        )

    async def _write_ticket_done(
        self, card: TodoCard, board: TodoBoard, actor: uuid.UUID | None
    ) -> None:
        ticket_ids = [
            edge.target_id
            for edge in await link_store.edges(self.session, "todo", [card.id], ("ticket",))
        ]
        for ticket_id in ticket_ids:
            self.session.add(
                TicketEvent(
                    id=uuid.uuid4(),
                    ticket_id=ticket_id,
                    actor_id=actor,
                    kind="todo_done",
                    payload={
                        "cardId": str(card.id),
                        "cardTitle": card.title,
                        "boardId": str(board.id),
                    },
                    created_at=_now(),
                )
            )

    def _mail(
        self,
        kind: MailKind,
        card: TodoCard,
        recipients: Iterable[uuid.UUID],
        actor: uuid.UUID,
        excerpt: str | None = None,
    ) -> None:
        others = tuple(dict.fromkeys(r for r in recipients if r != actor))
        if others:
            self.outbox.append(TodoMail(kind, card.id, others, actor, excerpt))

    async def _check_assignees(self, board: TodoBoard, ids: Iterable[uuid.UUID]) -> None:
        wanted = set(ids)
        if wanted and not wanted <= await self.access.member_ids(board):
            raise _invalid(
                "Assignees must be members of the board.", "assignee_not_allowed", "assigneeIds"
            )

    async def _check_event(self, board: TodoBoard, payload: EventIn) -> None:
        """Check the event data of a card on ``board``.

        Raises:
            ValidationProblem: ``event_personal_board`` (a personal board has no Events),
                ``event_dates_invalid`` (an end without a start or before the start),
                ``event_time_without_date`` (a time without its date) or
                ``series_not_found`` (HTTP 422).
        """
        if board.kind == "personal":
            raise _invalid(
                "A card on a personal board cannot be an Event.", "event_personal_board", "event"
            )
        if payload.ends_on is not None and (
            payload.starts_on is None or payload.ends_on < payload.starts_on
        ):
            raise _invalid("The end is before the start.", "event_dates_invalid", "endsOn")
        if (payload.start_time is not None and payload.starts_on is None) or (
            payload.end_time is not None and payload.ends_on is None
        ):
            raise _invalid("A time needs its date.", "event_time_without_date", "startTime")
        if (
            payload.start_time is not None
            and payload.end_time is not None
            and payload.ends_on == payload.starts_on
            and payload.end_time < payload.start_time
        ):
            raise _invalid("The end is before the start.", "event_dates_invalid", "endTime")
        if (
            payload.series_id is not None
            and await self.session.get(TodoEventSeries, payload.series_id) is None
        ):
            raise _invalid("The series was not found.", "series_not_found", "seriesId")

    async def _shared_boards(self, principal: Principal) -> list[TodoBoard]:
        """The live gremium and team boards that the principal reads."""
        if not token_reads(principal):
            return []
        scope = await self.access.scope(principal)
        return list(
            (
                await self.session.scalars(
                    select(TodoBoard).where(
                        scope.condition(),
                        TodoBoard.kind != "personal",
                        TodoBoard.archived_at.is_(None),
                    )
                )
            ).all()
        )

    async def _writes_shared_board(self, principal: Principal) -> bool:
        for board in await self._shared_boards(principal):
            if await self.access.can_write(board, principal):
                return True
        return False
