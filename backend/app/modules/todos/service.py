"""To-do service: boards, columns, labels, cards and their sub-resources.

The service decides every right itself (``BoardAccess``): a board, a card or a
sub-resource that the caller cannot read answers 404, a card write on a board that
the caller reads but cannot write (``todo.read_all``) answers 403
``todo_write_required``, and a configuration change without ``todo.configure``
answers 403 ``todo_configure_required``.

Writes that order cards (create, move, column delete) lock the board row first, so
two parallel moves compute their ranks one after the other. Every card write bumps
``todo_board.updated_at``. A write that changes a card sets its ``updated_at`` itself:
the column default ``onupdate=now()`` would expire the attribute, and the response
built after the commit would then load it outside the async context. ``version``
guards the content edits only (title, description, due date): moves and
sub-resources neither need nor bump it, so a drag never invalidates an open drawer.

A card that enters the done column gets ``completed_at`` and writes ``todo_done``
into the timeline of every linked ticket; a card that leaves it loses
``completed_at``.

Mails go through ``outbox``: the router sends them after the commit.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import accumulate
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import JsonValue
from sqlalchemy import ColumnElement, and_, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.people import DELETED_PERSON, PersonRef, person_refs
from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_message_drafts
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.files.service import FilesService
from app.modules.tickets.models import TicketEvent
from app.modules.todos import events as todo_events
from app.modules.todos.access import BoardAccess, ReadScope, token_reads
from app.modules.todos.boards import ensure_personal_board
from app.modules.todos.grouping import grouped
from app.modules.todos.lexorank import MAX_LENGTH, RankError, between, spread
from app.modules.todos.link_view import LinkViewer
from app.modules.todos.links import HIDDEN, LinkRef, LinkResolver, Resolved
from app.modules.todos.live import BoardPings
from app.modules.todos.models import (
    LINK_COLUMNS,
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoCardEvent,
    TodoCardLabel,
    TodoCheckItem,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoEventSeries,
    TodoLabel,
    TodoLink,
)
from app.modules.todos.schemas import (
    BoardPatch,
    CardCreate,
    CardMove,
    CardPatch,
    CardTransfer,
    CheckItemPatch,
    ChecklistCount,
    ColumnPatch,
    EventIn,
    LabelCreate,
    LabelPatch,
    TodoAssignedBoard,
    TodoBoardOut,
    TodoBoardSummary,
    TodoCardDetail,
    TodoCardTile,
    TodoCheckItemOut,
    TodoColumnOut,
    TodoColumnRef,
    TodoCommentOut,
    TodoEventBrief,
    TodoEventDecision,
    TodoEventEdition,
    TodoEventFacts,
    TodoEventOut,
    TodoEventRef,
    TodoEventSeriesOut,
    TodoEventTotals,
    TodoLabelOut,
    TodoLinkedCard,
    TodoLinkOut,
    TodoLinkView,
    TodoMember,
    TodoMine,
    TodoMineItem,
)
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.paging import Page
from app.shared.search import dialect_of, escape_like, trigram_rank

#: The local calendar of the due dates ("due within 7 days", "due tomorrow").
BERLIN = ZoneInfo("Europe/Berlin")
#: An open card due within this many days counts in ``dueSoonCount``.
DUE_SOON_DAYS = 7
#: The length of the comment excerpt in the mention mail.
EXCERPT_LENGTH = 200

MailKind = Literal["assigned", "mentioned"]
_KIND_ORDER = {"personal": 0, "gremium": 1, "team": 2}


def _now() -> datetime:
    return datetime.now(UTC)


def berlin_today(now: datetime | None = None) -> date:
    """Return today's date in Europe/Berlin."""
    return (now or _now()).astimezone(BERLIN).date()


def _iso_date(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _invalid(msg: str, code: str, field_name: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field_name, "msg": msg}])


@dataclass(frozen=True, slots=True)
class TodoMail:
    """A mail that the router sends after the commit.

    ``event_id`` is new for every mail and goes into the idempotency key, because
    the key is the arq job id: a second assignment or an identical mention on the
    same card would otherwise reuse the key and arq would drop it.
    """

    kind: MailKind
    card_id: uuid.UUID
    recipients: tuple[uuid.UUID, ...]
    actor_id: uuid.UUID
    excerpt: str | None = None
    event_id: uuid.UUID = field(default_factory=uuid.uuid4, compare=False)


@dataclass(frozen=True, slots=True)
class CardLink:
    """A link as a card shows it: its own links and the links of other cards to it.

    A link of card B to card A shows on A as a link of the kind ``todo`` to B, with the id
    of the row (spec 000573).
    """

    id: uuid.UUID
    kind: str
    target_id: uuid.UUID


def card_links(
    own: Iterable[TodoLink], incoming: Iterable[TodoLink]
) -> dict[uuid.UUID, tuple[CardLink, ...]]:
    """The links of each card: its own first, then the cards that link it, each target once."""
    pairs = (
        *((link.card_id, CardLink(link.id, link.kind, link.target_id)) for link in own),
        *(
            (link.todo_id, CardLink(link.id, "todo", link.card_id))
            for link in incoming
            if link.todo_id is not None
        ),
    )
    return {card_id: _first_per_target(group) for card_id, group in grouped(pairs).items()}


def _first_per_target(links: Sequence[CardLink]) -> tuple[CardLink, ...]:
    """Keep the first link to each target, in order: a link in each direction shows once."""
    first = {(c.kind, c.target_id): c for c in reversed(links)}
    return tuple(first[key] for key in dict.fromkeys((c.kind, c.target_id) for c in links))


@dataclass(frozen=True, slots=True)
class _Facts:
    """What the tiles of a set of cards show, loaded in one query per kind."""

    labels: Mapping[uuid.UUID, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    assignees: Mapping[uuid.UUID, tuple[uuid.UUID, ...]] = field(default_factory=dict)
    checklist: Mapping[uuid.UUID, tuple[int, int]] = field(default_factory=dict)
    comments: Mapping[uuid.UUID, int] = field(default_factory=dict)
    links: Mapping[uuid.UUID, tuple[CardLink, ...]] = field(default_factory=dict)
    people: Mapping[uuid.UUID, PersonRef] = field(default_factory=dict)
    resolved: Mapping[tuple[str, uuid.UUID], Resolved] = field(default_factory=dict)
    events: Mapping[uuid.UUID, TodoCardEvent] = field(default_factory=dict)
    series: Mapping[uuid.UUID, str] = field(default_factory=dict)


def _event_brief(
    row: TodoCardEvent | None, series: Mapping[uuid.UUID, str]
) -> TodoEventBrief | None:
    if row is None:
        return None
    return TodoEventBrief(
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        place=row.place,
        participants=row.participants,
        series_id=row.series_id,
        series_name=series.get(row.series_id) if row.series_id is not None else None,
    )


def _totals_out(value: todo_events.Totals) -> TodoEventTotals:
    return TodoEventTotals(
        requested=todo_events.balance_text(value.requested),
        approved=todo_events.balance_text(value.approved),
        expenses=todo_events.balance_text(value.expenses),
        income=todo_events.balance_text(value.income),
        balance=todo_events.balance_text(value.balance),
    )


def _link_out(link: CardLink, resolved: Mapping[tuple[str, uuid.UUID], Resolved]) -> TodoLinkOut:
    target = resolved.get((link.kind, link.target_id), HIDDEN)
    return TodoLinkOut(
        id=link.id,
        kind=link.kind,  # pyright: ignore[reportArgumentType]
        target_id=link.target_id,
        accessible=target.accessible,
        title=target.title if target.accessible else None,
        url=target.url if target.accessible else None,
        detail=target.detail if target.accessible else None,
        granted=target.granted,
    )


def _label_out(label: TodoLabel) -> TodoLabelOut:
    return TodoLabelOut(id=label.id, name=label.name, color=label.color)  # pyright: ignore[reportArgumentType]


def _mine_item(
    tile: TodoCardTile, board: TodoBoard, column: TodoColumn, labels: Mapping[uuid.UUID, TodoLabel]
) -> TodoMineItem:
    """Build a card of ``GET /todos/mine`` from its tile, its board and its column."""
    return TodoMineItem(
        **tile.model_dump(by_alias=False),
        board_name=board.name,
        board_kind=board.kind,  # pyright: ignore[reportArgumentType]
        column_name=column.name,
        labels=[_label_out(labels[i]) for i in tile.label_ids if i in labels],
    )


def _linked_order(card: TodoLinkedCard) -> tuple[bool, bool, bool, date, str]:
    """Sort key of the back-references: Events first, then open cards, each by due date."""
    return (
        card.event is None,
        card.is_done,
        card.due_date is None,
        card.due_date or date.max,
        card.title,
    )


def _assigned_board(
    board: TodoBoard,
    columns: Sequence[TodoColumn],
    labels: Iterable[TodoLabel],
    cards: Sequence[TodoCard],
    facts: _Facts,
    *,
    can_write: bool,
) -> TodoAssignedBoard:
    """Build a board row of ``mine_boards`` or ``all_boards`` from cards in board order."""
    return TodoAssignedBoard(
        id=board.id,
        name=board.name,
        kind=board.kind,  # pyright: ignore[reportArgumentType]
        gremium_id=board.gremium_id,
        can_write=can_write,
        columns=_column_outs(columns, Counter(c.column_id for c in cards)),
        labels=[_label_out(lab) for lab in labels],
        cards=[_tile(c, facts) for c in cards],
    )


def _board_order(board: TodoBoard) -> tuple[int, str, str]:
    """Sort key of the boards: personal, then gremium, then team, each by name."""
    return (_KIND_ORDER.get(board.kind, 3), board.name.casefold(), str(board.id))


def _in_column_order(cards: Iterable[TodoCard], columns: Sequence[TodoColumn]) -> list[TodoCard]:
    """Order the cards by the position of their column, then by rank.

    A card of a column that is not in ``columns`` goes last.
    """
    position = {c.id: index for index, c in enumerate(columns)}
    return sorted(cards, key=lambda c: (position.get(c.column_id, len(columns)), c.rank, str(c.id)))


def _column_outs(
    columns: Iterable[TodoColumn], per_column: Mapping[uuid.UUID, int]
) -> tuple[TodoColumnOut, ...]:
    """Build the columns of a board with the count of their cards."""
    return tuple(
        TodoColumnOut(
            id=c.id,
            name=c.name,
            position=c.position,
            is_done=c.is_done,
            card_count=per_column.get(c.id, 0),
        )
        for c in columns
    )


def _tile(card: TodoCard, facts: _Facts) -> TodoCardTile:
    """Build the tile of a card from the facts of its read."""
    done, total = facts.checklist.get(card.id, (0, 0))
    links = facts.links.get(card.id, ())
    assignees = sorted(
        (facts.people.get(pid, DELETED_PERSON) for pid in facts.assignees.get(card.id, ())),
        key=lambda p: ((p.display_name or "").casefold(), str(p.principal_id)),
    )
    return TodoCardTile(
        id=card.id,
        board_id=card.board_id,
        column_id=card.column_id,
        rank=card.rank,
        title=card.title,
        due_date=card.due_date,
        completed_at=card.completed_at,
        label_ids=sorted(facts.labels.get(card.id, ()), key=str),
        assignees=tuple(assignees),
        checklist=ChecklistCount(done=done, total=total),
        comment_count=facts.comments.get(card.id, 0),
        primary_link=_link_out(links[0], facts.resolved) if links else None,
        link_count=len(links),
        event=_event_brief(facts.events.get(card.id), facts.series),
        version=card.version,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


class TodoService:
    """To-do operations bound to an ``AsyncSession``."""

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
        """Raise 403 ``todo_write_required`` for a readable board that is not writable."""
        if not await self.access.can_write(board, principal):
            raise ForbiddenError(
                "Changing the cards of this board needs todo.write.",
                code="todo_write_required",
            )

    async def _configurable(self, board_id: uuid.UUID, principal: Principal) -> TodoBoard:
        board = await self._board(board_id, principal)
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
        link_rows = (
            await self.session.scalars(
                select(TodoLink)
                .where(or_(TodoLink.card_id.in_(ids), TodoLink.todo_id.in_(ids)))
                .order_by(TodoLink.created_at, TodoLink.id)
            )
        ).all()
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
        self, ids: set[uuid.UUID], rows: Sequence[TodoLink], principal: Principal
    ) -> tuple[dict[uuid.UUID, tuple[CardLink, ...]], dict[LinkRef, Resolved]]:
        """The links of the cards ``ids`` and the resolved first link of each card.

        ``rows`` holds the links of the cards and the links of other cards to them. A card
        shows the cards that link it, when the principal reads that card (spec 000573).
        """
        own = [link for link in rows if link.card_id in ids]
        to_them = [link for link in rows if link.todo_id in ids]
        firsts = {link.card_id: (link.kind, link.target_id) for link in reversed(own)}
        resolved = await self.links.resolve(
            {*firsts.values(), *(("todo", link.card_id) for link in to_them)}, principal
        )
        readable = [
            link for link in to_them if resolved.get(("todo", link.card_id), HIDDEN).accessible
        ]
        return card_links(own, readable), resolved

    async def tiles(self, cards: Sequence[TodoCard], principal: Principal) -> list[TodoCardTile]:
        """Build the tiles of the cards (in the given order)."""
        facts = await self._facts(cards, principal)
        return [_tile(c, facts) for c in cards]

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
        return [
            TodoBoardSummary(
                id=b.id,
                name=b.name,
                kind=b.kind,  # pyright: ignore[reportArgumentType]
                gremium_id=b.gremium_id,
                can_write=await self.access.can_write(b, principal),
                can_configure=await self.access.can_configure(b, principal),
                open_count=counts.get(b.id, 0),
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
        )

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

    async def add_column(
        self, board_id: uuid.UUID, name: str, principal: Principal
    ) -> TodoBoardOut:
        """Append a column."""
        board = await self._configurable(board_id, principal)
        columns = await self._columns(board.id)
        self.session.add(
            TodoColumn(
                id=uuid.uuid4(),
                board_id=board.id,
                name=name.strip() or name,
                position=(max(c.position for c in columns) + 1) if columns else 0,
                is_done=False,
            )
        )
        self._touch(board)
        await self.session.commit()
        return await self._board_out(board, principal)

    async def _column(self, board: TodoBoard, column_id: uuid.UUID) -> TodoColumn:
        """Load a column of the board, read again from the database.

        The callers take the board lock first, so ``is_done`` is the committed one: a
        parallel ``patch_column`` that moved the done flag has committed by then.
        """
        column = await self.session.get(TodoColumn, column_id, populate_existing=True)
        if column is None or column.board_id != board.id:
            raise NotFoundError(f"column {column_id} not found")
        return column

    async def patch_column(
        self,
        board_id: uuid.UUID,
        column_id: uuid.UUID,
        payload: ColumnPatch,
        principal: Principal,
    ) -> TodoBoardOut:
        """Rename a column, or make it the done column (``isDone: true`` moves the flag).

        The cards of the new done column get ``completed_at``; the cards of the old one
        lose it. Both include the archived cards, so a restored card has the state of
        its column. A live card that becomes done writes ``todo_done`` to its linked
        tickets, as a move into the done column does; an archived one does not.

        The partial unique index allows one done column, so the old flag is cleared and
        flushed before the new one is written.
        """
        board = await self._configurable(board_id, principal)
        await self._lock_board(board.id)
        column = await self._column(board, column_id)
        if payload.name is not None:
            column.name = payload.name.strip() or column.name
        if payload.is_done and not column.is_done:
            actor = await self._actor(principal)
            now = _now()
            for other in await self._columns(board.id):
                if other.is_done:
                    other.is_done = False
                    for card in await self._all_column_cards(other.id):
                        card.completed_at = None
                        card.updated_at = now
            await self.session.flush()
            column.is_done = True
            for card in await self._all_column_cards(column.id):
                card.updated_at = now
                if card.completed_at is None:
                    card.completed_at = now
                    if card.archived_at is None:
                        await self._write_ticket_done(card, board, actor)
        self._touch(board)
        await self.session.commit()
        return await self._board_out(board, principal)

    async def order_columns(
        self, board_id: uuid.UUID, column_ids: Sequence[uuid.UUID], principal: Principal
    ) -> TodoBoardOut:
        """Order the columns as given; the list names every column once.

        Raises:
            ValidationProblem: The list does not name exactly the columns (HTTP 422).
        """
        board = await self._configurable(board_id, principal)
        columns = {c.id: c for c in await self._columns(board.id)}
        if len(column_ids) != len(columns) or set(column_ids) != set(columns):
            raise _invalid(
                "columnIds names every column of the board once.", "invalid", "columnIds"
            )
        for position, column_id in enumerate(column_ids):
            columns[column_id].position = position
        self._touch(board)
        await self.session.commit()
        return await self._board_out(board, principal)

    async def delete_column(
        self,
        board_id: uuid.UUID,
        column_id: uuid.UUID,
        principal: Principal,
        *,
        move_to: uuid.UUID | None = None,
    ) -> TodoBoardOut:
        """Delete a column. Its cards (archived ones too) go to ``move_to`` first.

        Each card gets a ``moved`` event; a card that enters the done column this way
        gets ``completed_at``; a live one also writes ``todo_done`` to its linked
        tickets, an archived one does not.

        Raises:
            ConflictError: The done column (``done_column_required``), or cards and no
                ``move_to`` (``column_not_empty``) (HTTP 409).
            ValidationProblem: ``move_to`` is this column or not on the board (HTTP 422).

        The board lock comes before the read of ``is_done``, because a parallel
        ``patch_column`` can make this column the done column until then.
        """
        board = await self._configurable(board_id, principal)
        await self._lock_board(board.id)
        column = await self._column(board, column_id)
        if column.is_done:
            raise ConflictError("The done column cannot be deleted.", code="done_column_required")
        cards = await self._all_column_cards(column.id)
        if cards:
            if move_to is None:
                raise ConflictError("The column still has cards.", code="column_not_empty")
            target = await self.session.get(TodoColumn, move_to)
            if target is None or target.board_id != board.id or target.id == column.id:
                raise _invalid("moveTo names another column of the board.", "invalid", "moveTo")
            actor = await self._actor(principal)
            live = await self._column_cards(target.id)
            _append(live, cards)
            now = _now()
            for card in cards:
                self._event(
                    card,
                    "moved",
                    actor,
                    {
                        "fromColumnId": str(column.id),
                        "fromColumnName": column.name,
                        "toColumnId": str(target.id),
                        "toColumnName": target.name,
                    },
                )
                card.column_id = target.id
                card.updated_at = now
                if target.is_done and card.completed_at is None:
                    card.completed_at = now
                    if card.archived_at is None:
                        await self._write_ticket_done(card, board, actor)
            await self.session.flush()
        await self.session.delete(column)
        await self.session.flush()
        for position, other in enumerate(await self._columns(board.id)):
            other.position = position
        self._touch(board)
        await self.session.commit()
        return await self._board_out(board, principal)

    async def _label_name_taken(
        self, board_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None
    ) -> bool:
        others = (TodoLabel.id != exclude,) if exclude is not None else ()
        stmt = select(TodoLabel.id).where(
            TodoLabel.board_id == board_id, func.lower(TodoLabel.name) == name.lower(), *others
        )
        return await self.session.scalar(stmt) is not None

    async def add_label(
        self, board_id: uuid.UUID, payload: LabelCreate, principal: Principal
    ) -> TodoLabelOut:
        """Add a label. A name the board has (case-insensitive) gives 409 ``label_exists``."""
        board = await self._configurable(board_id, principal)
        await self._lock_board(board.id)
        name = payload.name.strip() or payload.name
        if await self._label_name_taken(board.id, name):
            raise ConflictError("The board has a label with this name.", code="label_exists")
        label = TodoLabel(id=uuid.uuid4(), board_id=board.id, name=name, color=payload.color)
        self.session.add(label)
        self._touch(board)
        await self.session.commit()
        return _label_out(label)

    async def _label(self, board: TodoBoard, label_id: uuid.UUID) -> TodoLabel:
        label = await self.session.get(TodoLabel, label_id)
        if label is None or label.board_id != board.id:
            raise NotFoundError(f"label {label_id} not found")
        return label

    async def patch_label(
        self,
        board_id: uuid.UUID,
        label_id: uuid.UUID,
        payload: LabelPatch,
        principal: Principal,
    ) -> TodoLabelOut:
        """Rename a label or change its color."""
        board = await self._configurable(board_id, principal)
        label = await self._label(board, label_id)
        if payload.name is not None:
            name = payload.name.strip() or payload.name
            if await self._label_name_taken(board.id, name, exclude=label.id):
                raise ConflictError("The board has a label with this name.", code="label_exists")
            label.name = name
        if payload.color is not None:
            label.color = payload.color
        self._touch(board)
        await self.session.commit()
        return _label_out(label)

    async def delete_label(
        self, board_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> None:
        """Delete a label; it leaves every card."""
        board = await self._configurable(board_id, principal)
        label = await self._label(board, label_id)
        await self.session.delete(label)
        self._touch(board)
        await self.session.commit()

    async def card(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Return the whole card, archived ones too.

        Raises:
            NotFoundError: The card is unknown or its board not readable (HTTP 404).
        """
        card, board = await self._card(card_id, principal)
        return await self._detail(card, board, principal)

    async def link_view(
        self, card_id: uuid.UUID, link_id: uuid.UUID, principal: Principal
    ) -> TodoLinkView:
        """Return the read sheet of one link of a card (spec 000487).

        A reader of the card reads its links, also those that the rule of their kind
        hides. A ticket and a gremium have no sheet.

        Raises:
            NotFoundError: The card is not readable, the link is not on the card, or the
                target has no sheet (HTTP 404).
        """
        card, _board = await self._card(card_id, principal)
        link = await self._card_link(card, link_id)
        return await LinkViewer(self.session, self.links).view(link.kind, link.target_id, principal)

    async def _card_link(self, card: TodoCard, link_id: uuid.UUID) -> CardLink:
        """One link as ``card`` shows it: its own, or the link of another card to it (000573).

        Raises:
            NotFoundError: The link is neither on the card nor to the card (HTTP 404).
        """
        link = await self.session.get(TodoLink, link_id)
        if link is not None and link.card_id == card.id:
            return CardLink(link.id, link.kind, link.target_id)
        if link is not None and link.todo_id == card.id:
            return CardLink(link.id, "todo", link.card_id)
        raise NotFoundError(f"link {link_id} not found")

    async def cards(
        self, card_ids: Sequence[uuid.UUID], principal: Principal
    ) -> list[TodoCardDetail]:
        """Return the whole cards of ``card_ids`` in their order, archived ones too.

        The read-ahead of the board page reads many cards in one request. A card that
        is unknown or whose board the caller cannot read is left out, as the single
        read answers 404 for it. A repeated id gives one card.
        """
        ids = list(dict.fromkeys(card_ids))
        found = {
            card.id: card
            for card in (
                await self.session.scalars(select(TodoCard).where(TodoCard.id.in_(ids)))
            ).all()
        }
        boards = {
            board.id: board
            for board in (
                await self.session.scalars(
                    select(TodoBoard).where(TodoBoard.id.in_({c.board_id for c in found.values()}))
                )
            ).all()
        }
        known = [
            (found[card_id], boards[found[card_id].board_id]) for card_id in ids if card_id in found
        ]
        pairs = [
            (card, board) for card, board in known if await self.access.can_read(board, principal)
        ]
        return await self._details(pairs, principal)

    async def tile(self, card_id: uuid.UUID, principal: Principal) -> TodoCardTile:
        """Return the tile of a live card, the same one that the board read holds.

        A live ping names a card, and the page reads its tile here.

        Raises:
            NotFoundError: The card is unknown, archived or not readable (HTTP 404).
        """
        card, _board = await self._card(card_id, principal)
        if card.archived_at is not None:
            raise NotFoundError(f"card {card_id} not found")
        return (await self.tiles([card], principal))[0]

    async def _detail(
        self, card: TodoCard, board: TodoBoard, principal: Principal
    ) -> TodoCardDetail:
        return (await self._details([(card, board)], principal))[0]

    async def _details(
        self, pairs: Sequence[tuple[TodoCard, TodoBoard]], principal: Principal
    ) -> list[TodoCardDetail]:
        """Build the whole cards of ``pairs`` with a fixed number of queries per board."""
        cards = [card for card, _board in pairs]
        ids = [card.id for card in cards]
        facts = await self._facts(cards, principal)
        boards = {board.id: board for _card, board in pairs}
        columns = {board_id: await self._columns(board_id) for board_id in boards}
        board_labels = {board_id: await self._labels(board_id) for board_id in boards}
        writable = {
            board_id: await self.access.can_write(board, principal)
            for board_id, board in boards.items()
        }
        items = _by_card(
            (
                await self.session.scalars(
                    select(TodoCheckItem)
                    .where(TodoCheckItem.card_id.in_(ids))
                    .order_by(TodoCheckItem.position, TodoCheckItem.id)
                )
            ).all()
        )
        events = _by_card(
            (
                await self.session.scalars(
                    select(TodoEvent)
                    .where(TodoEvent.card_id.in_(ids))
                    .order_by(TodoEvent.created_at, TodoEvent.id)
                )
            ).all()
        )
        comments = _by_card(
            (
                await self.session.scalars(
                    select(TodoComment)
                    .where(TodoComment.card_id.in_(ids), TodoComment.deleted_at.is_(None))
                    .order_by(TodoComment.created_at, TodoComment.id)
                )
            ).all()
        )
        resolved = await self.links.resolve(_detail_refs(cards, facts, events), principal)
        persons = await person_refs(self.session, _detail_people(cards, events, comments))
        me = await self.access.me(principal)
        files = await self.files.message_attachments(
            "todo_comment", [c.id for card in cards for c in comments.get(card.id, ())]
        )
        gathered = await self._event_facts(
            [card for card in cards if card.id in facts.events], facts, principal
        )
        parts = _DetailParts(
            facts=facts,
            columns=columns,
            board_labels=board_labels,
            writable=writable,
            items=items,
            events=events,
            comments=comments,
            resolved=resolved,
            persons=persons,
            me=me,
            files=files,
            gathered=gathered,
        )
        return [parts.detail(card, board) for card, board in pairs]

    async def _event_facts(
        self, cards: Sequence[TodoCard], facts: _Facts, principal: Principal
    ) -> dict[uuid.UUID, TodoEventFacts]:
        """The totals, decisions and other editions of the Events among ``cards``."""
        if not cards:
            return {}
        readable = (await self.access.scope(principal)).condition()
        found = {
            card.id: await todo_events.editions(
                self.session, card, facts.events[card.id].series_id, readable
            )
            for card in cards
        }
        ids = [
            *(card.id for card in cards),
            *(other.id for rows, _hidden in found.values() for other, _b, _e in rows),
        ]
        sums = await todo_events.totals(self.session, list(dict.fromkeys(ids)))
        decided = {card.id: await todo_events.decisions(self.session, card.id) for card in cards}
        return {
            card.id: TodoEventFacts(
                totals=_totals_out(sums[card.id]),
                decisions=tuple(_decision_out(d) for d in decided[card.id]),
                editions=[
                    _edition_out(other, board, row, sums) for other, board, row in found[card.id][0]
                ],
                hidden_editions=found[card.id][1],
            )
            for card in cards
        }

    async def _check_assignees(self, board: TodoBoard, ids: Iterable[uuid.UUID]) -> None:
        wanted = set(ids)
        if wanted and not wanted <= await self.access.member_ids(board):
            raise _invalid(
                "Assignees must be members of the board.", "assignee_not_allowed", "assigneeIds"
            )

    async def create(self, payload: CardCreate, principal: Principal) -> TodoCardDetail:
        """Create a card at the end of its column (default: the first column).

        ``event`` makes the card an Event (spec 000478). ``checklist`` holds the open items
        of a duplicate (spec 000554).

        Raises:
            NotFoundError: The board is unknown or not readable (HTTP 404).
            ValidationProblem: ``column_not_on_board``, ``assignee_not_allowed``,
                ``label_not_on_board``, ``link_target_not_found`` or an event error of
                ``_check_event`` (HTTP 422).
            ConflictError: ``event_link_taken`` (HTTP 409).
        """
        actor = await self._actor(principal)
        board = await self._board(payload.board_id, principal, write=True)
        await self._lock_board(board.id)
        columns = await self._columns(board.id)
        column = _pick_column(columns, payload.column_id)
        assignees = list(dict.fromkeys(payload.assignee_ids))
        await self._check_assignees(board, assignees)
        label_ids = list(dict.fromkeys(payload.label_ids))
        if label_ids and not set(label_ids) <= {label.id for label in await self._labels(board.id)}:
            raise _invalid("A label is not on this board.", "label_not_on_board", "labelIds")
        links = list(dict.fromkeys((link.kind, link.target_id) for link in payload.links))
        for kind, target_id in links:
            if not await self.links.readable(kind, target_id, principal):
                raise _invalid("The link target was not found.", "link_target_not_found", "links")
        if payload.event is not None:
            await self._check_event(board, payload.event)
            await todo_events.check_one_event(self.session, uuid.uuid4(), links)
        live = await self._column_cards(column.id)
        now = _now()
        card = TodoCard(
            id=uuid.uuid4(),
            board_id=board.id,
            column_id=column.id,
            rank="",
            title=payload.title.strip() or payload.title,
            description_md=payload.description_md,
            due_date=payload.due_date,
            created_by=actor,
            completed_at=now if column.is_done else None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        _append(live, [card])
        self.session.add(card)
        await self.session.flush()
        for principal_id in assignees:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=principal_id))
        for label_id in label_ids:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
        for kind, target_id in links:
            self.session.add(_new_link(card.id, kind, target_id, actor))
        for position, text in enumerate(payload.checklist):
            self.session.add(
                TodoCheckItem(
                    id=uuid.uuid4(),
                    card_id=card.id,
                    text=text.strip() or text,
                    done=False,
                    position=position,
                )
            )
        if payload.event is not None:
            self.session.add(_event_row(card.id, payload.event))
        self._event(card, "created", actor)
        await self.session.flush()
        if column.is_done:
            await self._write_ticket_done(card, board, actor)
        self._touch(board, card)
        await self.session.commit()
        self._mail("assigned", card, assignees, actor)
        return await self._detail(card, board, principal)

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

    async def patch(
        self, card_id: uuid.UUID, payload: CardPatch, principal: Principal
    ) -> TodoCardDetail:
        """Change the title, the description or the due date (``version`` required).

        Raises:
            NotFoundError: The card is unknown or not readable (HTTP 404).
            ConflictError: ``version`` is not the current one (HTTP 409,
                ``card_version_conflict``).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if payload.version != card.version:
            raise ConflictError(
                "The card was changed in the meantime.", code="card_version_conflict"
            )
        fields = payload.model_fields_set
        title = (
            (payload.title.strip() or payload.title) if payload.title is not None else card.title
        )
        renamed = title != card.title
        described = "description_md" in fields and payload.description_md != card.description_md
        redated = "due_date" in fields and payload.due_date != card.due_date
        if renamed:
            self._event(card, "renamed", actor, {"from": card.title, "to": title})
            card.title = title
        if described:
            card.description_md = payload.description_md
        if redated:
            self._event(
                card,
                "due",
                actor,
                {"from": _iso_date(card.due_date), "to": _iso_date(payload.due_date)},
            )
            card.due_date = payload.due_date
        if renamed or described or redated:
            card.version += 1
            card.updated_at = _now()
            self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def move(
        self, card_id: uuid.UUID, payload: CardMove, principal: Principal
    ) -> TodoCardTile:
        """Move a card into a column, between ``afterId`` (above) and ``beforeId`` (below).

        Without neighbors the card goes to the end of the column. A change of the
        column writes a ``moved`` event; the entry into the done column sets
        ``completed_at`` and writes ``todo_done`` to the linked tickets.

        Raises:
            NotFoundError: The card is unknown or not readable (HTTP 404).
            ConflictError: ``card_moved``: a parallel transfer moved the card to
                another board while the move waited for the board lock (HTTP 409).
            ValidationProblem: ``column_not_on_board``, or ``rank_neighbors_invalid``
                for a neighbor outside the column or two neighbors that are not
                adjacent (HTTP 422).

        After the lock the card is read again, because a parallel move of the same card
        can have held the lock, and the column change must work from the committed
        column. A reorder that ranks every card of the column touches the board, so the
        board reads again.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, write=True)
        await self._lock_board(board.id)
        await self.session.refresh(card)
        if card.board_id != board.id:
            raise _card_moved()
        columns = {c.id: c for c in await self._columns(board.id)}
        target = columns.get(payload.column_id)
        if target is None:
            raise _invalid("The column is not on this board.", "column_not_on_board", "columnId")
        siblings = await self._column_cards(target.id, exclude=card.id)
        respread = _place(siblings, _slot(siblings, payload.after_id, payload.before_id), card)
        source = columns.get(card.column_id)
        if target.id != card.column_id:
            self._event(
                card,
                "moved",
                actor,
                {
                    "fromColumnId": str(card.column_id),
                    "fromColumnName": source.name if source is not None else "",
                    "toColumnId": str(target.id),
                    "toColumnName": target.name,
                },
            )
            card.column_id = target.id
            if target.is_done:
                card.completed_at = _now()
                await self._write_ticket_done(card, board, actor)
            else:
                card.completed_at = None
        card.updated_at = _now()
        self._touch(board, card)
        if respread:
            self._touch(board)
        await self.session.commit()
        return (await self.tiles([card], principal))[0]

    async def transfer(
        self, card_id: uuid.UUID, payload: CardTransfer, principal: Principal
    ) -> TodoCardDetail:
        """Move a card into a column of another board (default: the first column).

        The card goes between ``afterId`` (above) and ``beforeId`` (below), the same
        neighbors as ``move``; without them it goes to the end of the column.

        Labels are per board: a label of the card stays when the target board has a
        label with the same name (case-insensitive), else it is dropped. The service
        never creates a label on the target, because that needs ``todo.configure``.
        Assignees who are not members of the target board are dropped, without a mail.
        Links, comments, the checklist and the events stay with the card. A card
        without an assignee that leaves the actor's personal board gets the actor as
        assignee when the actor is a member of the target (no mail), so it stays in
        "Meine To-Dos".

        A card of a shared board (gremium or team) never moves into a personal board
        (403 ``transfer_to_personal``), because its comments, files and links would
        then leave the reach of everyone else on the board.

        Both boards are locked in id order, so two transfers between the same two
        boards in opposite directions wait instead of deadlocking.

        Raises:
            NotFoundError: The card or the target board is unknown or not readable
                (HTTP 404).
            ForbiddenError: ``todo_write_required`` for a board that the caller reads
                but cannot write, ``transfer_to_personal`` from a shared board into a
                personal board (HTTP 403).
            ConflictError: ``card_moved`` (a parallel transfer moved the card) or
                ``card_archived`` (HTTP 409).
            ValidationProblem: ``transfer_same_board``, ``column_not_on_board``, or
                ``rank_neighbors_invalid`` for a neighbor outside the target column
                (HTTP 422).

        Every read comes before the first change of the card, because a read after it
        autoflushes the card, and an UPDATE without ``updated_at`` expires it.
        """
        actor = await self._actor(principal)
        card, source = await self._card(card_id, principal, write=True)
        if payload.board_id == source.id:
            raise _invalid(
                "The card is on this board already. Use move.", "transfer_same_board", "boardId"
            )
        target = await self._board(payload.board_id, principal, write=True)
        _check_transfer_kinds(source, target)
        for board_id in sorted((source.id, target.id)):
            await self._lock_board(board_id)
        await self.session.refresh(card)
        if card.board_id != source.id:
            raise _card_moved()
        if card.archived_at is not None:
            raise ConflictError("An archived card cannot move.", code="card_archived")
        columns = await self._columns(target.id)
        column = _pick_column(columns, payload.column_id)
        from_column = await self.session.get(TodoColumn, card.column_id)
        own_labels = list(
            (
                await self.session.scalars(
                    select(TodoLabel)
                    .join(TodoCardLabel, TodoCardLabel.label_id == TodoLabel.id)
                    .where(TodoCardLabel.card_id == card.id)
                    .order_by(func.lower(TodoLabel.name), TodoLabel.id)
                )
            ).all()
        )
        by_name = {label.name.lower(): label for label in await self._labels(target.id)}
        matched = {label.id: by_name.get(label.name.lower()) for label in own_labels}
        kept = list(dict.fromkeys(m.id for m in matched.values() if m is not None))
        dropped_labels: list[JsonValue] = [
            label.name for label in own_labels if matched[label.id] is None
        ]
        assignees = set(
            (
                await self.session.scalars(
                    select(TodoAssignee.principal_id).where(TodoAssignee.card_id == card.id)
                )
            ).all()
        )
        members = await self.access.member_ids(target)
        dropped_assignees = assignees - members
        claim = source.kind == "personal" and not assignees and actor in members
        live = await self._column_cards(column.id)
        index = _slot(live, payload.after_id, payload.before_id)
        await self.session.execute(delete(TodoCardLabel).where(TodoCardLabel.card_id == card.id))
        if dropped_assignees:
            await self.session.execute(
                delete(TodoAssignee).where(
                    TodoAssignee.card_id == card.id,
                    TodoAssignee.principal_id.in_(dropped_assignees),
                )
            )
        now = _now()
        card.updated_at = now
        for label_id in kept:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
        self._event(
            card,
            "moved",
            actor,
            {
                "fromColumnId": str(card.column_id),
                "fromColumnName": from_column.name if from_column is not None else "",
                "toColumnId": str(column.id),
                "toColumnName": column.name,
                "fromBoardId": str(source.id),
                "fromBoardName": source.name,
                "toBoardId": str(target.id),
                "toBoardName": target.name,
                "droppedLabels": dropped_labels,
                "droppedAssignees": len(dropped_assignees),
            },
        )
        if claim:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=actor))
            self._event(card, "assigned", actor, {"principalId": str(actor), "added": True})
        respread = _place(live, index, card)
        card.board_id = target.id
        card.column_id = column.id
        if not column.is_done:
            card.completed_at = None
        elif card.completed_at is None:
            card.completed_at = now
            await self._write_ticket_done(card, target, actor)
        self._touch(source, card, removed=True)
        self._touch(target, card)
        if respread:
            self._touch(target)
        await self.session.commit()
        return await self._detail(card, target, principal)

    async def complete(self, card: TodoCard, board: TodoBoard, actor: uuid.UUID) -> bool:
        """Move an open card to the end of the done column, without a commit.

        Returns:
            True when the card moved (False: no done column, done already, archived,
            or a parallel transfer moved it to another board).

        The board lock orders this rank against a parallel move or create, and the card
        is read again after the lock.
        """
        await self._lock_board(board.id)
        await self.session.refresh(card)
        if card.board_id != board.id:
            return False
        columns = await self._columns(board.id)
        done = next((c for c in columns if c.is_done), None)
        if done is None or card.column_id == done.id or card.archived_at is not None:
            return False
        source = next((c for c in columns if c.id == card.column_id), None)
        live = await self._column_cards(done.id, exclude=card.id)
        _append(live, [card])
        self._event(
            card,
            "moved",
            actor,
            {
                "fromColumnId": str(card.column_id),
                "fromColumnName": source.name if source is not None else "",
                "toColumnId": str(done.id),
                "toColumnName": done.name,
            },
        )
        card.column_id = done.id
        card.completed_at = _now()
        card.updated_at = _now()
        await self._write_ticket_done(card, board, actor)
        self._touch(board, card)
        await self.session.flush()
        return True

    async def _write_ticket_done(
        self, card: TodoCard, board: TodoBoard, actor: uuid.UUID | None
    ) -> None:
        ticket_ids = (
            await self.session.scalars(
                select(TodoLink.ticket_id).where(
                    TodoLink.card_id == card.id, TodoLink.ticket_id.is_not(None)
                )
            )
        ).all()
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

    async def archive_card(self, card_id: uuid.UUID, principal: Principal) -> None:
        """Archive a card (``DELETE``); a second call changes nothing."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if card.archived_at is None:
            card.archived_at = card.updated_at = _now()
            self._event(card, "archived", actor)
            self._touch(board, card, removed=True)
            await self.session.commit()

    async def restore_card(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Bring an archived card back into its column.

        A card in the done column gets a new ``completed_at``, else the archive cron
        archives it again at its next run.

        The column is read before the card changes, because a later read autoflushes the
        card. ``completed_at`` would then go in a second UPDATE without an explicit
        ``updated_at``, and its ``onupdate=now()`` expires the attribute.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if card.archived_at is not None:
            column = await self.session.get(TodoColumn, card.column_id)
            card.archived_at = None
            card.updated_at = _now()
            if column is not None and column.is_done:
                card.completed_at = card.updated_at
            self._event(card, "restored", actor)
            self._touch(board, card)
            await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_assignee(
        self, card_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Assign a member of the board (422 ``assignee_not_allowed`` otherwise).

        The board lock makes a parallel identical request wait and then see the row.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        await self._check_assignees(board, [principal_id])
        present = await self.session.scalar(
            select(TodoAssignee.principal_id).where(
                TodoAssignee.card_id == card.id, TodoAssignee.principal_id == principal_id
            )
        )
        if present is None:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=principal_id))
            self._event(card, "assigned", actor, {"principalId": str(principal_id), "added": True})
            self._touch(board, card)
            await self.session.commit()
            self._mail("assigned", card, [principal_id], actor)
        return await self._detail(card, board, principal)

    async def remove_assignee(
        self, card_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Remove an assignee; an unknown one changes nothing."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        result = await self.session.execute(
            delete(TodoAssignee).where(
                TodoAssignee.card_id == card.id, TodoAssignee.principal_id == principal_id
            )
        )
        if getattr(result, "rowcount", 0):
            self._event(card, "assigned", actor, {"principalId": str(principal_id), "added": False})
            self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_card_label(
        self, card_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Put a label of the board on the card (422 ``label_not_on_board`` otherwise)."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        label = await self.session.get(TodoLabel, label_id)
        if label is None or label.board_id != board.id:
            raise _invalid("The label is not on this board.", "label_not_on_board", "labelId")
        present = await self.session.scalar(
            select(TodoCardLabel.label_id).where(
                TodoCardLabel.card_id == card.id, TodoCardLabel.label_id == label_id
            )
        )
        if present is None:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
            self._touch(board, card)
            await self.session.commit()
        return await self._detail(card, board, principal)

    async def remove_card_label(
        self, card_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Take a label off the card."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        await self.session.execute(
            delete(TodoCardLabel).where(
                TodoCardLabel.card_id == card.id, TodoCardLabel.label_id == label_id
            )
        )
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_check_item(
        self, card_id: uuid.UUID, text: str, principal: Principal
    ) -> TodoCardDetail:
        """Append a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        last = await self.session.scalar(
            select(func.max(TodoCheckItem.position)).where(TodoCheckItem.card_id == card.id)
        )
        value = text.strip() or text
        self.session.add(
            TodoCheckItem(
                id=uuid.uuid4(),
                card_id=card.id,
                text=value,
                done=False,
                position=(last + 1) if last is not None else 0,
            )
        )
        self._event(card, "checklist", actor, {"action": "added", "text": value})
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def _check_item(self, card: TodoCard, item_id: uuid.UUID) -> TodoCheckItem:
        item = await self.session.get(TodoCheckItem, item_id)
        if item is None or item.card_id != card.id:
            raise NotFoundError(f"checklist item {item_id} not found")
        return item

    async def patch_check_item(
        self,
        card_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: CheckItemPatch,
        principal: Principal,
    ) -> TodoCardDetail:
        """Rename, tick or untick, or move a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        item = await self._check_item(card, item_id)
        if payload.text is not None:
            value = payload.text.strip() or payload.text
            if value != item.text:
                item.text = value
                self._event(card, "checklist", actor, {"action": "renamed", "text": value})
        if payload.done is not None and payload.done != item.done:
            item.done = payload.done
            action = "done" if payload.done else "undone"
            self._event(card, "checklist", actor, {"action": action, "text": item.text})
        if payload.position is not None:
            items = list(
                (
                    await self.session.scalars(
                        select(TodoCheckItem)
                        .where(TodoCheckItem.card_id == card.id)
                        .order_by(TodoCheckItem.position, TodoCheckItem.id)
                    )
                ).all()
            )
            others = [i for i in items if i.id != item.id]
            at = min(payload.position, len(others))
            for position, entry in enumerate([*others[:at], item, *others[at:]]):
                entry.position = position
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def delete_check_item(
        self, card_id: uuid.UUID, item_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Delete a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        item = await self._check_item(card, item_id)
        await self.session.delete(item)
        self._event(card, "checklist", actor, {"action": "removed", "text": item.text})
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_link(
        self, card_id: uuid.UUID, kind: str, target_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Link the card to a target that the caller reads.

        Raises:
            ValidationProblem: ``link_self`` or ``link_target_not_found`` (HTTP 422).
            ConflictError: The link exists (``link_exists``), or the card is an Event and
                another Event links the Antrag, Buchung or invoice (``event_link_taken``)
                (HTTP 409).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if kind == "todo" and target_id == card.id:
            raise _invalid("A card cannot link to itself.", "link_self", "targetId")
        if not await self.links.readable(kind, target_id, principal):
            raise _invalid("The link target was not found.", "link_target_not_found", "targetId")
        column = getattr(TodoLink, LINK_COLUMNS[kind])
        present = await self.session.scalar(
            select(TodoLink.id).where(_link_between(card.id, kind, target_id, column))
        )
        if present is not None:
            raise ConflictError("The card has this link.", code="link_exists")
        if await self.session.get(TodoCardEvent, card.id) is not None:
            await todo_events.check_one_event(self.session, card.id, [(kind, target_id)])
        self.session.add(_new_link(card.id, kind, target_id, actor))
        self._event(card, "linked", actor, {"linkKind": kind, "targetId": str(target_id)})
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def _check_event(self, board: TodoBoard, payload: EventIn) -> None:
        """Check the event data of a card on ``board``.

        Raises:
            ValidationProblem: ``event_personal_board`` (a personal board has no Events),
                ``event_dates_invalid`` (an end without a start or before the start) or
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
        if (
            payload.series_id is not None
            and await self.session.get(TodoEventSeries, payload.series_id) is None
        ):
            raise _invalid("The series was not found.", "series_not_found", "seriesId")

    async def set_event(
        self, card_id: uuid.UUID, payload: EventIn, principal: Principal
    ) -> TodoCardDetail:
        """Set the event data of a card; a to-do becomes an Event (spec 000488).

        Raises:
            ValidationProblem: An error of ``_check_event`` (HTTP 422).
            ConflictError: ``event_link_taken`` when a to-do becomes an Event and another
                Event links one of its Anträge, Buchungen or invoices (HTTP 409).
        """
        await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        await self._check_event(board, payload)
        row = await self.session.get(TodoCardEvent, card.id)
        if row is None:
            refs = [
                (link.kind, link.target_id)
                for link in (
                    await self.session.scalars(select(TodoLink).where(TodoLink.card_id == card.id))
                ).all()
            ]
            await todo_events.check_one_event(self.session, card.id, refs)
            self.session.add(_event_row(card.id, payload))
        else:
            row.starts_on = payload.starts_on
            row.ends_on = payload.ends_on
            row.place = _clean(payload.place)
            row.participants = payload.participants
            row.series_id = payload.series_id
        card.updated_at = _now()
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def remove_event(self, card_id: uuid.UUID, principal: Principal) -> None:
        """Refuse to remove the event data: an Event never becomes a to-do again.

        Raises:
            NotFoundError: The card is not an Event (HTTP 404).
            ConflictError: ``event_permanent`` (HTTP 409, spec 000488).
        """
        card, _board = await self._card(card_id, principal, write=True)
        if await self.session.get(TodoCardEvent, card.id) is None:
            raise NotFoundError(f"card {card_id} is not an Event")
        raise ConflictError("An Event cannot become a to-do again.", code="event_permanent")

    async def follow_up(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Create the next edition of an Event in the first column (spec 000484).

        The new card gets the title, the description, the labels, the place, the series
        and the checklist with every item open. It gets no links, assignees, comments,
        dates or history.

        An archived Event can be the source, because the previous edition is usually
        archived.

        Raises:
            ValidationProblem: ``not_an_event`` (HTTP 422).
        """
        actor = await self._actor(principal)
        source, board = await self._card(card_id, principal, lock=True, write=True)
        row = await self.session.get(TodoCardEvent, source.id)
        if row is None:
            raise _invalid("The card is not an Event.", "not_an_event", "cardId")
        column = (await self._columns(board.id))[0]
        label_ids = list(
            (
                await self.session.scalars(
                    select(TodoCardLabel.label_id).where(TodoCardLabel.card_id == source.id)
                )
            ).all()
        )
        items = list(
            (
                await self.session.scalars(
                    select(TodoCheckItem)
                    .where(TodoCheckItem.card_id == source.id)
                    .order_by(TodoCheckItem.position, TodoCheckItem.id)
                )
            ).all()
        )
        live = await self._column_cards(column.id)
        now = _now()
        card = TodoCard(
            id=uuid.uuid4(),
            board_id=board.id,
            column_id=column.id,
            rank="",
            title=source.title,
            description_md=source.description_md,
            due_date=None,
            created_by=actor,
            completed_at=now if column.is_done else None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        _append(live, [card])
        self.session.add(card)
        await self.session.flush()
        for label_id in label_ids:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
        for item in items:
            self.session.add(
                TodoCheckItem(
                    id=uuid.uuid4(),
                    card_id=card.id,
                    text=item.text,
                    done=False,
                    position=item.position,
                )
            )
        self.session.add(TodoCardEvent(card_id=card.id, place=row.place, series_id=row.series_id))
        self._event(card, "created", actor)
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def series(self, q: str | None, principal: Principal) -> list[TodoEventSeriesOut]:
        """List the series by name (at most 50), filtered by ``q``."""
        await self._actor(principal)
        term = (q or "").strip()
        named = (TodoEventSeries.name.ilike(f"%{escape_like(term)}%", escape="\\"),) if term else ()
        stmt = select(TodoEventSeries).where(*named)
        rows = (
            await self.session.scalars(stmt.order_by(func.lower(TodoEventSeries.name)).limit(50))
        ).all()
        return [TodoEventSeriesOut(id=row.id, name=row.name) for row in rows]

    async def create_series(self, name: str, principal: Principal) -> TodoEventSeriesOut:
        """Create a series; its name is unique in the platform, case ignored.

        Each person who writes a shared board can create a series (spec 000483).

        Raises:
            ForbiddenError: ``todo_write_required`` (HTTP 403).
            ValidationProblem: ``series_name_blank`` (HTTP 422).
            ConflictError: ``series_exists`` (HTTP 409).
        """
        actor = await self._actor(principal)
        if not await self._writes_shared_board(principal):
            raise ForbiddenError(
                "Creating a series needs todo.write on a shared board.",
                code="todo_write_required",
            )
        value = name.strip()
        if not value:
            raise _invalid("The name is empty.", "series_name_blank", "name")
        taken = await self.session.scalar(
            select(TodoEventSeries.id).where(func.lower(TodoEventSeries.name) == value.lower())
        )
        if taken is not None:
            raise ConflictError("A series with this name exists.", code="series_exists")
        row = TodoEventSeries(id=uuid.uuid4(), name=value, created_by=actor)
        self.session.add(row)
        await self.session.commit()
        return TodoEventSeriesOut(id=row.id, name=row.name)

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

    async def writable_events(self, q: str | None, principal: Principal) -> list[TodoEventRef]:
        """The live Events on boards that the caller writes: the options of the picker.

        Spec 000480: the ``Veranstaltung`` picker of a Buchung lists only these.
        """
        boards = {
            board.id: board
            for board in await self._shared_boards(principal)
            if await self.access.can_write(board, principal)
        }
        if not boards:
            return []
        term = (q or "").strip()
        titled = (TodoCard.title.ilike(f"%{escape_like(term)}%", escape="\\"),) if term else ()
        stmt = (
            select(TodoCard, TodoCardEvent)
            .join(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
            .where(TodoCard.board_id.in_(boards), TodoCard.archived_at.is_(None), *titled)
        )
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(
                        TodoCardEvent.starts_on.desc().nulls_first(), TodoCard.created_at.desc()
                    ).limit(100)
                )
            )
            .tuples()
            .all()
        )
        return [
            TodoEventRef(
                id=card.id,
                board_id=card.board_id,
                board_name=boards[card.board_id].name,
                title=card.title,
                starts_on=row.starts_on,
                ends_on=row.ends_on,
            )
            for card, row in rows
        ]

    async def remove_link(
        self, card_id: uuid.UUID, link_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Remove a link of the card.

        A link between two cards goes from either card, and with it every link between
        the two (spec 000573).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        link = await self._card_link(card, link_id)
        payload: dict[str, JsonValue] = {"linkKind": link.kind, "targetId": str(link.target_id)}
        column = getattr(TodoLink, LINK_COLUMNS[link.kind])
        await self.session.execute(
            delete(TodoLink).where(_link_between(card.id, link.kind, link.target_id, column))
        )
        self._event(card, "unlinked", actor, payload)
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def _check_mentions(self, board: TodoBoard, mentions: Sequence[uuid.UUID]) -> None:
        if mentions and not set(mentions) <= await self.access.member_ids(board):
            raise _invalid(
                "Mentions must be members of the board.", "mention_not_member", "mentions"
            )

    async def add_comment(
        self,
        card_id: uuid.UUID,
        body: str,
        mentions: Sequence[uuid.UUID],
        principal: Principal,
        *,
        attachment_ids: Sequence[uuid.UUID] = (),
        draft_token: str | None = None,
        pepper: str = "",
    ) -> TodoCommentOut:
        """Add a comment and bind its files; new mentions get the mail ``todo_mentioned``.

        The method locks the board and then the card before the insert, because the
        insert takes a key-share lock on the card and the commit updates the board. In
        the other order it deadlocks with the Gremium delete and the erasure, which
        lock the board and then the cards ``FOR UPDATE``.

        Raises:
            NotFoundError: The card is not readable (HTTP 404).
            ValidationProblem: A mention outside the board, files without a draft
                token, or a draft that is missing, expired, foreign or infected
                (HTTP 422).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        wanted = list(dict.fromkeys(mentions))
        await self._check_mentions(board, wanted)
        token = await check_message_drafts(
            self.session, attachment_ids=attachment_ids, token=draft_token, pepper=pepper
        )
        comment = TodoComment(
            id=uuid.uuid4(),
            card_id=card.id,
            author_id=actor,
            body=body,
            mentions=[str(m) for m in wanted],
            created_at=_now(),
        )
        self.session.add(comment)
        if token is not None:
            await self.session.flush()
            await bind_drafts(
                self.session,
                attachment_ids=attachment_ids,
                token=token,
                pepper=pepper,
                todo_comment_id=comment.id,
            )
        self._touch(board, card)
        await self.session.commit()
        self._mail("mentioned", card, wanted, actor, _excerpt(body))
        return await self._comment(comment, actor)

    async def _own_comment(
        self, card: TodoCard, comment_id: uuid.UUID, principal: Principal
    ) -> tuple[TodoComment, uuid.UUID]:
        comment = await self.session.get(TodoComment, comment_id)
        if comment is None or comment.card_id != card.id or comment.deleted_at is not None:
            raise NotFoundError(f"comment {comment_id} not found")
        me = await self.access.me(principal)
        if me is None or comment.author_id != me:
            raise ForbiddenError("Only the author edits a comment.", code="not_comment_author")
        return comment, me

    async def edit_comment(
        self,
        card_id: uuid.UUID,
        comment_id: uuid.UUID,
        body: str,
        mentions: Sequence[uuid.UUID],
        principal: Principal,
    ) -> TodoCommentOut:
        """Change an own comment; mentions that are new get the mail."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        comment, me = await self._own_comment(card, comment_id, principal)
        wanted = list(dict.fromkeys(mentions))
        await self._check_mentions(board, wanted)
        before = {_uuid_of(m) for m in comment.mentions or []}
        comment.body = body
        comment.mentions = [str(m) for m in wanted]
        comment.edited_at = _now()
        self._touch(board, card)
        await self.session.commit()
        self._mail("mentioned", card, [m for m in wanted if m not in before], me, _excerpt(body))
        return await self._comment(comment, me)

    async def delete_comment(
        self, card_id: uuid.UUID, comment_id: uuid.UUID, principal: Principal
    ) -> None:
        """Soft-delete an own comment and remove its files."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        comment, _me = await self._own_comment(card, comment_id, principal)
        comment.deleted_at = _now()
        await self.files.delete_for_messages("todo_comment", [comment.id], actor=principal.sub)
        self._touch(board, card)
        await self.session.commit()

    async def _comment(self, comment: TodoComment, me: uuid.UUID) -> TodoCommentOut:
        persons = await person_refs(self.session, frozenset(_comment_people(comment)))
        files = await self.files.message_attachments("todo_comment", [comment.id])
        return _comment_out(comment, persons, me, files.get(comment.id, ()))

    async def mine(self, principal: Principal) -> TodoMine:
        """The open cards assigned to the caller over every readable board.

        ``dueSoonCount`` counts the ones due within 7 days (overdue included).

        Raises:
            ForbiddenError: A token whose scope allows none of ``todo.write``,
                ``todo.all`` and ``todo.read_all`` (HTTP 403).
        """
        if not token_reads(principal):
            raise ForbiddenError("The token scope does not allow to-dos.")
        me = await self.access.me(principal)
        if me is None:
            return TodoMine()
        scope = await self.access.scope(principal)
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard, TodoColumn)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .join(TodoAssignee, TodoAssignee.card_id == TodoCard.id)
                .where(
                    TodoAssignee.principal_id == me,
                    TodoCard.archived_at.is_(None),
                    TodoColumn.is_done.is_(False),
                    TodoBoard.archived_at.is_(None),
                    scope.condition(),
                )
                .order_by(
                    TodoCard.due_date.asc().nulls_last(), TodoCard.updated_at.desc(), TodoCard.id
                )
            )
        ).all()
        if not rows:
            return TodoMine()
        cards = [card for card, _board, _column in rows]
        facts = await self._facts(cards, principal)
        labels = {
            label.id: label
            for label in (
                await self.session.scalars(
                    select(TodoLabel).where(
                        TodoLabel.board_id.in_({card.board_id for card in cards})
                    )
                )
            ).all()
        }
        limit = berlin_today() + timedelta(days=DUE_SOON_DAYS)
        items = [
            _mine_item(_tile(card, facts), board, column, labels) for card, board, column in rows
        ]
        due_soon = sum(1 for c in cards if c.due_date is not None and c.due_date <= limit)
        return TodoMine(items=items, due_soon_count=due_soon)

    async def mine_boards(self, principal: Principal) -> list[TodoAssignedBoard]:
        """The shared boards that hold live cards assigned to the caller, with only those cards.

        The rows under "Meine To-Dos": every readable board except the personal one, on
        which at least one live card (done ones too) names the caller as an assignee.
        A board comes with all its columns in their order and its labels; the read
        scope keeps out every board that the caller cannot read, also when a card of
        it still names the caller. Order: the gremium boards by name, then team.

        Raises:
            ForbiddenError: A token whose scope allows none of ``todo.write``,
                ``todo.all`` and ``todo.read_all`` (HTTP 403).
        """
        return await self._board_rows(principal, mine=True)

    async def all_boards(self, principal: Principal) -> list[TodoAssignedBoard]:
        """Every readable board with all its live cards (the meta-board "Alle").

        The personal board comes first (the call creates it when it is missing, like
        ``list_boards``), then the gremium boards by name, then the team boards. A
        board comes with all its columns in their order, its labels and every live
        card; ``cardCount`` counts the live cards of each column.

        Raises:
            ForbiddenError: A token whose scope allows none of ``todo.write``,
                ``todo.all`` and ``todo.read_all`` (HTTP 403).
        """
        return await self._board_rows(principal, mine=False)

    async def _board_rows(self, principal: Principal, *, mine: bool) -> list[TodoAssignedBoard]:
        """Build the board rows of ``mine_boards`` (``mine``) or ``all_boards``.

        The number of queries does not depend on the number of boards: one for the
        boards or the cards, one each for the columns and the labels, and the tile
        facts of all cards together.
        """
        if not token_reads(principal):
            raise ForbiddenError("The token scope does not allow to-dos.")
        me = await self.access.me(principal)
        if mine and me is None:
            return []
        if not mine and me is not None:
            await ensure_personal_board(self.session, me)
        scope = await self.access.scope(principal)
        boards, cards = (
            await self._assigned_cards(me, scope)
            if mine and me is not None
            else await self._live_cards(scope)
        )
        if not boards:
            return []
        column_rows = (
            await self.session.scalars(
                select(TodoColumn)
                .where(TodoColumn.board_id.in_(boards))
                .order_by(TodoColumn.position, TodoColumn.id)
            )
        ).all()
        label_rows = (
            await self.session.scalars(
                select(TodoLabel)
                .where(TodoLabel.board_id.in_(boards))
                .order_by(func.lower(TodoLabel.name), TodoLabel.id)
            )
        ).all()
        facts = await self._facts(cards, principal)
        columns = grouped((col.board_id, col) for col in column_rows)
        labels = grouped((lab.board_id, lab) for lab in label_rows)
        per_board = grouped((c.board_id, c) for c in cards)
        return [
            _assigned_board(
                b,
                columns.get(b.id, ()),
                labels.get(b.id, ()),
                _in_column_order(per_board.get(b.id, ()), columns.get(b.id, ())),
                facts,
                can_write=await self.access.can_write(b, principal),
            )
            for b in sorted(boards.values(), key=_board_order)
        ]

    async def _assigned_cards(
        self, me: uuid.UUID, scope: ReadScope
    ) -> tuple[dict[uuid.UUID, TodoBoard], list[TodoCard]]:
        """The live cards on shared boards that name ``me``, and their boards."""
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoAssignee, TodoAssignee.card_id == TodoCard.id)
                .where(
                    TodoAssignee.principal_id == me,
                    TodoCard.archived_at.is_(None),
                    TodoBoard.archived_at.is_(None),
                    TodoBoard.kind != "personal",
                    scope.condition(),
                )
                .order_by(TodoCard.rank, TodoCard.id)
            )
        ).all()
        return {b.id: b for _card, b in rows}, [c for c, _b in rows]

    async def _live_cards(
        self, scope: ReadScope
    ) -> tuple[dict[uuid.UUID, TodoBoard], list[TodoCard]]:
        """The live boards in ``scope`` and every live card on them."""
        boards = {
            b.id: b
            for b in (
                await self.session.scalars(
                    select(TodoBoard).where(scope.condition(), TodoBoard.archived_at.is_(None))
                )
            ).all()
        }
        cards = (
            list(
                (
                    await self.session.scalars(
                        select(TodoCard)
                        .where(TodoCard.board_id.in_(boards), TodoCard.archived_at.is_(None))
                        .order_by(TodoCard.rank, TodoCard.id)
                    )
                ).all()
            )
            if boards
            else []
        )
        return boards, cards

    async def linked(
        self, kind: str, target_id: uuid.UUID, principal: Principal
    ) -> list[TodoLinkedCard]:
        """The readable live cards that link to a target.

        A linked Event is first and carries its dates, its place and its balance (spec
        000489). Then come the open cards, then the done cards, each by due date.
        """
        if not token_reads(principal):
            return []
        scope = await self.access.scope(principal)
        column = getattr(TodoLink, LINK_COLUMNS[kind])
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard, TodoColumn)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .join(TodoLink, TodoLink.card_id == TodoCard.id)
                .where(column == target_id, TodoCard.archived_at.is_(None), scope.condition())
            )
        ).all()
        if not rows:
            return []
        facts = await self._facts([card for card, _b, _c in rows], principal)
        sums = await todo_events.totals(
            self.session, [card.id for card, _b, _c in rows if card.id in facts.events]
        )
        found = [
            TodoLinkedCard(
                id=card.id,
                board_id=board.id,
                board_name=board.name,
                title=card.title,
                column_name=col.name,
                is_done=col.is_done,
                due_date=card.due_date,
                assignees=_tile(card, facts).assignees,
                event=_event_brief(facts.events.get(card.id), facts.series),
                balance=(
                    todo_events.balance_text(sums[card.id].balance) if card.id in sums else None
                ),
            )
            for card, board, col in rows
        ]
        return sorted(found, key=_linked_order)

    async def search(
        self, q: str, principal: Principal, *, limit: int
    ) -> list[tuple[TodoCard, TodoBoard, TodoColumn]]:
        """Find live cards by title on the boards that the principal reads (palette)."""
        if not token_reads(principal):
            return []
        scope = await self.access.scope(principal)
        where, rank = trigram_rank(q, [TodoCard.title], dialect=dialect_of(self.session))
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard, TodoColumn)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .where(
                    where,
                    scope.condition(),
                    TodoCard.archived_at.is_(None),
                    TodoBoard.archived_at.is_(None),
                )
                .order_by(rank.desc(), TodoCard.updated_at.desc())
                .limit(limit)
            )
        ).all()
        return [(card, board, column) for card, board, column in rows]

    async def search_events(
        self, q: str, principal: Principal, *, limit: int
    ) -> list[tuple[TodoCard, TodoBoard, TodoCardEvent]]:
        """Find Events by title on the boards that the principal reads, archived ones too.

        Spec 000485: the palette source ``Veranstaltungen`` finds archived Events.
        """
        if not token_reads(principal):
            return []
        scope = await self.access.scope(principal)
        where, rank = trigram_rank(q, [TodoCard.title], dialect=dialect_of(self.session))
        rows = (
            (
                await self.session.execute(
                    select(TodoCard, TodoBoard, TodoCardEvent)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .join(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
                    .where(where, scope.condition())
                    .order_by(rank.desc(), TodoCardEvent.starts_on.desc().nulls_last(), TodoCard.id)
                    .limit(limit)
                )
            )
            .tuples()
            .all()
        )
        return list(rows)

    async def calendar_events(
        self, principal: Principal
    ) -> list[tuple[TodoCard, TodoBoard, TodoCardEvent]]:
        """The Events with a start on the boards that the principal reads (spec 000486).

        Archived Events stay in the feed, because an archived Event still took place.
        """
        if not token_reads(principal):
            return []
        scope = await self.access.scope(principal)
        rows = (
            (
                await self.session.execute(
                    select(TodoCard, TodoBoard, TodoCardEvent)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .join(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
                    .where(scope.condition(), TodoCardEvent.starts_on.is_not(None))
                    .order_by(TodoCardEvent.starts_on, TodoCard.id)
                )
            )
            .tuples()
            .all()
        )
        return list(rows)

    async def calendar_due_cards(self, principal: Principal) -> list[tuple[TodoCard, TodoBoard]]:
        """The open cards with a due date assigned to the principal (spec 000549).

        Only boards that the principal reads count. A done or archived card, a card on an
        archived board and an Event (the feed has it as an Event already) stay out.
        """
        if not token_reads(principal):
            return []
        me = await self.access.me(principal)
        if me is None:
            return []
        scope = await self.access.scope(principal)
        rows = (
            (
                await self.session.execute(
                    select(TodoCard, TodoBoard)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                    .join(TodoAssignee, TodoAssignee.card_id == TodoCard.id)
                    .outerjoin(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
                    .where(
                        TodoAssignee.principal_id == me,
                        TodoCard.due_date.is_not(None),
                        TodoCard.archived_at.is_(None),
                        TodoColumn.is_done.is_(False),
                        TodoBoard.archived_at.is_(None),
                        TodoCardEvent.card_id.is_(None),
                        scope.condition(),
                    )
                    .order_by(TodoCard.due_date, TodoCard.id)
                )
            )
            .tuples()
            .all()
        )
        return list(rows)

    async def calendar_due_between(
        self,
        principal: Principal,
        *,
        start: date | None = None,
        end: date | None = None,
        pattern: str | None = None,
        only_mine: bool = False,
        limit: int | None = None,
    ) -> list[tuple[TodoCard, TodoBoard, bool]]:
        """The open cards with a due date on every board that the principal reads.

        The Kalender shows them (spec 000712). ``start`` and ``end`` limit the due date,
        both ends included, and ``pattern`` is an ILIKE pattern for the title. A done or
        archived card, a card on an archived board and an Event stay out, as in
        `calendar_due_cards`.

        Returns:
            ``(card, board, mine)`` rows, where ``mine`` tells if the card is assigned
            to the principal. With ``only_mine`` every row is assigned. Without a
            span the newest due date comes first, for the search.
        """
        if not token_reads(principal):
            return []
        me = await self.access.me(principal)
        scope = await self.access.scope(principal)
        assigned = exists().where(
            TodoAssignee.card_id == TodoCard.id, TodoAssignee.principal_id == me
        )
        rows = (
            (
                await self.session.execute(
                    select(TodoCard, TodoBoard, assigned)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                    .outerjoin(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
                    .where(
                        TodoCard.due_date.is_not(None),
                        TodoCard.archived_at.is_(None),
                        TodoColumn.is_done.is_(False),
                        TodoBoard.archived_at.is_(None),
                        TodoCardEvent.card_id.is_(None),
                        scope.condition(),
                        *((TodoCard.due_date >= start,) if start is not None else ()),
                        *((TodoCard.due_date <= end,) if end is not None else ()),
                        *(
                            (TodoCard.title.ilike(pattern, escape="\\"),)
                            if pattern is not None
                            else ()
                        ),
                        *((assigned,) if only_mine else ()),
                    )
                    .order_by(
                        TodoCard.due_date if start is not None else TodoCard.due_date.desc(),
                        TodoCard.id,
                    )
                    .limit(limit)
                )
            )
            .tuples()
            .all()
        )
        return list(rows)

    async def calendar_events_between(
        self,
        principal: Principal,
        *,
        start: date | None = None,
        end: date | None = None,
        pattern: str | None = None,
        only_mine: bool = False,
        limit: int | None = None,
    ) -> list[tuple[TodoCard, TodoBoard, TodoCardEvent, bool]]:
        """The Events with a start on the boards that the principal reads, for the Kalender.

        ``start`` and ``end`` keep the Events with a day in the span. An Event without an
        end takes one day. Archived Events stay, as in `calendar_events`.

        Returns:
            ``(card, board, event, mine)`` rows, where ``mine`` tells if the Event is
            assigned to the principal.
        """
        if not token_reads(principal):
            return []
        me = await self.access.me(principal)
        scope = await self.access.scope(principal)
        assigned = exists().where(
            TodoAssignee.card_id == TodoCard.id, TodoAssignee.principal_id == me
        )
        last_day = func.coalesce(TodoCardEvent.ends_on, TodoCardEvent.starts_on)
        rows = (
            (
                await self.session.execute(
                    select(TodoCard, TodoBoard, TodoCardEvent, assigned)
                    .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                    .join(TodoCardEvent, TodoCardEvent.card_id == TodoCard.id)
                    .where(
                        scope.condition(),
                        TodoCardEvent.starts_on.is_not(None),
                        *((last_day >= start,) if start is not None else ()),
                        *((TodoCardEvent.starts_on <= end,) if end is not None else ()),
                        *(
                            (TodoCard.title.ilike(pattern, escape="\\"),)
                            if pattern is not None
                            else ()
                        ),
                        *((assigned,) if only_mine else ()),
                    )
                    .order_by(
                        TodoCardEvent.starts_on
                        if start is not None
                        else TodoCardEvent.starts_on.desc(),
                        TodoCard.id,
                    )
                    .limit(limit)
                )
            )
            .tuples()
            .all()
        )
        return list(rows)

    async def card_for_agenda(
        self, card_id: uuid.UUID, gremium_id: uuid.UUID, principal: Principal
    ) -> TodoCard:
        """Check a card for a new agenda item of a meeting of ``gremium_id``.

        The call locks the board of the card, then the card, before the agenda locks
        the meeting. A card create locks the board and then inserts a meeting link,
        which takes a key share on the meeting row, so every path takes the board
        first and the two cannot deadlock.

        Raises:
            NotFoundError: The card is unknown or not readable (HTTP 404).
            ValidationProblem: The card is archived (``todo_archived``) or not on the
                board of the gremium (``todo_wrong_board``) (HTTP 422).
        """
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if card.archived_at is not None:
            raise _invalid("The card is archived.", "todo_archived", "todoId")
        if board.kind != "gremium" or board.gremium_id != gremium_id:
            raise _invalid(
                "The card is not on the board of this gremium.", "todo_wrong_board", "todoId"
            )
        return card

    async def link_agenda_item(
        self, card: TodoCard, agenda_item_id: uuid.UUID, principal: Principal
    ) -> None:
        """Link the card to the agenda item when it is not linked yet. No commit."""
        actor = await self._actor(principal)
        present = await self.session.scalar(
            select(TodoLink.id).where(
                TodoLink.card_id == card.id, TodoLink.agenda_item_id == agenda_item_id
            )
        )
        if present is not None:
            return
        self.session.add(_new_link(card.id, "agenda_item", agenda_item_id, actor))
        self._event(
            card, "linked", actor, {"linkKind": "agenda_item", "targetId": str(agenda_item_id)}
        )
        board = await self.session.get(TodoBoard, card.board_id)
        if board is not None:
            self._touch(board, card)


def _check_transfer_kinds(source: TodoBoard, target: TodoBoard) -> None:
    """Refuse a transfer from a shared board into a personal board (403).

    Raises:
        ForbiddenError: ``transfer_to_personal``.
    """
    if source.kind != "personal" and target.kind == "personal":
        raise ForbiddenError(
            "A card of a shared board cannot move into a personal board.",
            code="transfer_to_personal",
        )


def _pick_column(columns: Sequence[TodoColumn], column_id: uuid.UUID | None) -> TodoColumn:
    """Return the column ``column_id`` of a board, or its first column for ``None``.

    Raises:
        ValidationProblem: The column is not on the board (HTTP 422, ``column_not_on_board``).
    """
    if column_id is None:
        return columns[0]
    found = next((c for c in columns if c.id == column_id), None)
    if found is None:
        raise _invalid("The column is not on this board.", "column_not_on_board", "columnId")
    return found


def _card_moved() -> ConflictError:
    return ConflictError("The card was moved in the meantime.", code="card_moved")


def _rank(low: str | None, high: str | None) -> str:
    """Return ``between(low, high)``, or raise RankError for a rank above ``MAX_LENGTH``."""
    rank = between(low, high)
    if len(rank) > MAX_LENGTH:
        raise RankError(f"rank longer than {MAX_LENGTH}")
    return rank


def _respread(ordered: Sequence[TodoCard]) -> None:
    """Give the cards a fresh order with ``spread``, in the order given."""
    now = _now()
    for card, rank in zip(ordered, spread(len(ordered)), strict=True):
        card.rank = rank
        card.updated_at = now


def _append(live: Sequence[TodoCard], cards: Sequence[TodoCard]) -> None:
    """Rank ``cards`` after the live cards ``live`` of a column, in the order given.

    A rank above ``MAX_LENGTH`` or a broken rank gives the live cards and ``cards``
    a fresh order. The caller holds the board lock, so no parallel write ranks the
    column at the same time.
    """
    try:
        ranks = _ranks_after(live[-1].rank if live else None, len(cards))
    except RankError:
        _respread([*live, *cards])
        return
    for card, rank in zip(cards, ranks, strict=True):
        card.rank = rank


def _ranks_after(last: str | None, count: int) -> tuple[str, ...]:
    """Return ``count`` ascending ranks after ``last`` (``None``: an empty column).

    Raises:
        RankError: A rank is broken or a new rank is longer than ``MAX_LENGTH``.
    """
    if count == 0:
        return ()
    first = _rank(last, None)
    return tuple(accumulate(range(count - 1), lambda rank, _: _rank(rank, None), initial=first))


def _place(live: Sequence[TodoCard], index: int, card: TodoCard) -> bool:
    """Rank ``card`` at ``index`` among the live cards ``live`` of a column.

    Two cards that share a rank, a broken rank or a new rank above ``MAX_LENGTH``
    give the column a fresh order. The
    caller holds the board lock, so no parallel write ranks the column at the same time.

    Returns:
        True when the column got a fresh order. The caller then pings the whole
        board, because the other cards of the column changed too.
    """
    low = live[index - 1].rank if index > 0 else None
    high = live[index].rank if index < len(live) else None
    try:
        card.rank = _rank(low, high)
    except RankError:
        _respread([*live[:index], card, *live[index:]])
        return True
    return False


def _slot(
    siblings: Sequence[TodoCard], after_id: uuid.UUID | None, before_id: uuid.UUID | None
) -> int:
    """Return the index in ``siblings`` where the moved card goes.

    Raises:
        ValidationProblem: A neighbor is not in the column, or the two neighbors are
            not adjacent (HTTP 422, ``rank_neighbors_invalid``).
    """
    index = {c.id: i for i, c in enumerate(siblings)}

    def at(card_id: uuid.UUID, name: str) -> int:
        if card_id not in index:
            raise _invalid("The neighbor is not in this column.", "rank_neighbors_invalid", name)
        return index[card_id]

    if after_id is not None and before_id is not None:
        above, below = at(after_id, "afterId"), at(before_id, "beforeId")
        if below != above + 1:
            raise _invalid("The neighbors are not adjacent.", "rank_neighbors_invalid", "beforeId")
        return below
    if before_id is not None:
        return at(before_id, "beforeId")
    if after_id is not None:
        return at(after_id, "afterId") + 1
    return len(siblings)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _event_row(card_id: uuid.UUID, payload: EventIn) -> TodoCardEvent:
    return TodoCardEvent(
        card_id=card_id,
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        place=_clean(payload.place),
        participants=payload.participants,
        series_id=payload.series_id,
    )


def _link_between(
    card_id: uuid.UUID,
    kind: str,
    target_id: uuid.UUID,
    column: Any,  # noqa: ANN401
) -> ColumnElement[bool]:
    """The links of the card to the target, and for a card target also its links back."""
    own = and_(TodoLink.card_id == card_id, column == target_id)
    if kind != "todo":
        return own
    return or_(own, and_(TodoLink.card_id == target_id, TodoLink.todo_id == card_id))


def _new_link(card_id: uuid.UUID, kind: str, target_id: uuid.UUID, actor: uuid.UUID) -> TodoLink:
    link = TodoLink(id=uuid.uuid4(), card_id=card_id, created_by=actor, created_at=_now())
    setattr(link, LINK_COLUMNS[kind], target_id)
    return link


def _by_card[R: (TodoCheckItem, TodoEvent, TodoComment)](
    rows: Iterable[R],
) -> dict[uuid.UUID, tuple[R, ...]]:
    """Group rows by their card and keep the order of the query."""
    return grouped((row.card_id, row) for row in rows)


def _event_people(event: TodoEvent) -> tuple[uuid.UUID | None, ...]:
    """The actor of an event and, for an assignment, the assignee."""
    assigned = (_uuid_of(event.payload.get("principalId")),) if event.kind == "assigned" else ()
    return (event.actor_id, *assigned)


def _comment_people(comment: TodoComment) -> tuple[uuid.UUID | None, ...]:
    """The author of a comment and the people it mentions."""
    return (comment.author_id, *(_uuid_of(m) for m in comment.mentions or []))


def _detail_people(
    cards: Iterable[TodoCard],
    events: Mapping[uuid.UUID, Sequence[TodoEvent]],
    comments: Mapping[uuid.UUID, Sequence[TodoComment]],
) -> frozenset[uuid.UUID | None]:
    """The people that the whole cards name: creators, event people and comment people."""
    return frozenset(
        person
        for card in cards
        for person in (
            card.created_by,
            *(p for event in events.get(card.id, ()) for p in _event_people(event)),
            *(p for comment in comments.get(card.id, ()) for p in _comment_people(comment)),
        )
    )


def _detail_refs(
    cards: Iterable[TodoCard], facts: _Facts, events: Mapping[uuid.UUID, Sequence[TodoEvent]]
) -> frozenset[tuple[str, uuid.UUID]]:
    """The link targets that the whole cards name: their links and the (un)link events."""
    linked = (
        (link.kind, link.target_id) for card in cards for link in facts.links.get(card.id, ())
    )
    logged = (
        _ref_of(event.payload)
        for card in cards
        for event in events.get(card.id, ())
        if event.kind in ("linked", "unlinked")
    )
    return frozenset((*linked, *(ref for ref in logged if ref is not None)))


def _decision_out(decision: todo_events.Decision) -> TodoEventDecision:
    amount = decision.amount
    return TodoEventDecision(
        kind=decision.kind,  # pyright: ignore[reportArgumentType]
        target_id=decision.target_id,
        title=decision.title,
        decided_at=decision.decided_at,
        meeting_title=decision.meeting_title,
        result=decision.result,
        amount=todo_events.balance_text(amount) if amount is not None else None,
        conditions=decision.conditions,
    )


def _edition_out(
    other: TodoCard,
    board: TodoBoard,
    row: TodoCardEvent,
    sums: Mapping[uuid.UUID, todo_events.Totals],
) -> TodoEventEdition:
    return TodoEventEdition(
        id=other.id,
        board_id=board.id,
        board_name=board.name,
        title=other.title,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        archived=other.archived_at is not None,
        totals=_totals_out(sums[other.id]),
    )


@dataclass(frozen=True, slots=True)
class _DetailParts:
    """What the whole cards of one read show, loaded before the first card is built."""

    facts: _Facts
    columns: Mapping[uuid.UUID, Sequence[TodoColumn]]
    board_labels: Mapping[uuid.UUID, Sequence[TodoLabel]]
    writable: Mapping[uuid.UUID, bool]
    items: Mapping[uuid.UUID, Sequence[TodoCheckItem]]
    events: Mapping[uuid.UUID, Sequence[TodoEvent]]
    comments: Mapping[uuid.UUID, Sequence[TodoComment]]
    resolved: Mapping[tuple[str, uuid.UUID], Resolved]
    persons: Mapping[uuid.UUID, PersonRef]
    me: uuid.UUID | None
    files: Mapping[uuid.UUID, list[MessageAttachmentOut]]
    gathered: Mapping[uuid.UUID, TodoEventFacts]

    def detail(self, card: TodoCard, board: TodoBoard) -> TodoCardDetail:
        """Build the whole card of ``card`` on ``board``."""
        tile = _tile(card, self.facts)
        own_labels = frozenset(tile.label_ids)
        labels = self.board_labels[board.id]
        return TodoCardDetail(
            **tile.model_dump(by_alias=False),
            description_md=card.description_md,
            board_name=board.name,
            board_kind=board.kind,  # pyright: ignore[reportArgumentType]
            can_write=self.writable[board.id],
            columns=tuple(
                TodoColumnRef(id=c.id, name=c.name, is_done=c.is_done)
                for c in self.columns[board.id]
            ),
            labels=tuple(_label_out(label) for label in labels if label.id in own_labels),
            board_labels=tuple(_label_out(label) for label in labels),
            created_by=self.persons.get(card.created_by, DELETED_PERSON),
            links=tuple(
                _link_out(link, self.resolved) for link in self.facts.links.get(card.id, ())
            ),
            checklist_items=tuple(
                TodoCheckItemOut(id=i.id, text=i.text, done=i.done, position=i.position)
                for i in self.items.get(card.id, ())
            ),
            events=tuple(
                _event_out(e, self.persons, self.resolved) for e in self.events.get(card.id, ())
            ),
            comments=tuple(
                _comment_out(c, self.persons, self.me, self.files.get(c.id, ()))
                for c in self.comments.get(card.id, ())
            ),
            archived_at=card.archived_at,
            event_facts=self.gathered.get(card.id),
        )


def _uuid_of(value: object) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


def _ref_of(payload: dict[str, Any]) -> tuple[str, uuid.UUID] | None:
    kind = payload.get("linkKind")
    target = _uuid_of(payload.get("targetId"))
    if kind in LINK_COLUMNS and target is not None:
        return (kind, target)
    return None


def _excerpt(body: str) -> str:
    flat = " ".join(body.split())
    return flat if len(flat) <= EXCERPT_LENGTH else flat[: EXCERPT_LENGTH - 1] + "…"


def _person(persons: Mapping[uuid.UUID, PersonRef], principal_id: uuid.UUID | None) -> PersonRef:
    if principal_id is None:
        return DELETED_PERSON
    return persons.get(principal_id, DELETED_PERSON)


def _event_payload(
    event: TodoEvent,
    persons: Mapping[uuid.UUID, PersonRef],
    resolved: Mapping[tuple[str, uuid.UUID], Resolved],
) -> dict[str, JsonValue]:
    """The payload of an event as the timeline shows it.

    An assignment names the person instead of its id; a link or an unlink carries the
    title of the target when the viewer reads it.
    """
    payload: dict[str, JsonValue] = dict(event.payload or {})
    match event.kind:
        case "assigned":
            person = _person(persons, _uuid_of(payload.get("principalId")))
            return {
                "person": person.model_dump(by_alias=True, mode="json"),
                "added": bool(payload.get("added", False)),
            }
        case "linked" | "unlinked":
            ref = _ref_of(payload)
            target = resolved.get(ref, HIDDEN) if ref is not None else HIDDEN
            return {**payload, "title": target.title if target.accessible else None}
        case _:
            return payload


def _event_out(
    event: TodoEvent,
    persons: Mapping[uuid.UUID, PersonRef],
    resolved: Mapping[tuple[str, uuid.UUID], Resolved],
) -> TodoEventOut:
    return TodoEventOut(
        id=event.id,
        kind=event.kind,  # pyright: ignore[reportArgumentType]
        actor=_person(persons, event.actor_id) if event.actor_id is not None else None,
        at=event.created_at,
        payload=_event_payload(event, persons, resolved),
    )


def _comment_out(
    comment: TodoComment,
    persons: Mapping[uuid.UUID, PersonRef],
    me: uuid.UUID | None,
    attachments: Sequence[MessageAttachmentOut] = (),
) -> TodoCommentOut:
    return TodoCommentOut(
        id=comment.id,
        author=_person(persons, comment.author_id),
        body=comment.body,
        mentions=tuple(_person(persons, _uuid_of(m)) for m in comment.mentions or []),
        at=comment.created_at,
        edited_at=comment.edited_at,
        is_own=me is not None and comment.author_id == me,
        attachments=list(attachments),
    )


__all__ = ["BERLIN", "TodoMail", "TodoService", "berlin_today"]
