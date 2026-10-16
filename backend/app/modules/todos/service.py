"""To-do service: boards, columns, labels, cards and their sub-resources.

The service decides every right itself (``BoardAccess``): a board, a card or a
sub-resource that the caller cannot read answers 404, and a configuration change
without ``todo.configure`` answers 403 ``todo_configure_required``.

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
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import JsonValue
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.tickets.models import TicketEvent
from app.modules.todos.access import TODO_WRITE, BoardAccess
from app.modules.todos.boards import ensure_personal_board
from app.modules.todos.lexorank import RankError, between, spread
from app.modules.todos.links import HIDDEN, LinkResolver, Resolved
from app.modules.todos.models import (
    LINK_COLUMNS,
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoCardLabel,
    TodoCheckItem,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoLabel,
    TodoLink,
)
from app.modules.todos.schemas import (
    BoardPatch,
    CardCreate,
    CardMove,
    CardPatch,
    CheckItemPatch,
    ChecklistCount,
    ColumnPatch,
    LabelCreate,
    LabelPatch,
    TodoBoardOut,
    TodoBoardSummary,
    TodoCardDetail,
    TodoCardTile,
    TodoCheckItemOut,
    TodoColumnOut,
    TodoColumnRef,
    TodoCommentOut,
    TodoEventOut,
    TodoLabelOut,
    TodoLinkedCard,
    TodoLinkOut,
    TodoMember,
    TodoMine,
    TodoMineItem,
)
from app.search import dialect_of, escape_like, trigram_rank
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.paging import Page
from app.shared.people import DELETED_PERSON, PersonRef, person_refs

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


@dataclass(slots=True)
class _Facts:
    """What the tiles of a set of cards show, loaded in one query per kind."""

    labels: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    assignees: dict[uuid.UUID, list[uuid.UUID]] = field(default_factory=dict)
    checklist: dict[uuid.UUID, tuple[int, int]] = field(default_factory=dict)
    comments: dict[uuid.UUID, int] = field(default_factory=dict)
    links: dict[uuid.UUID, list[TodoLink]] = field(default_factory=dict)
    people: dict[uuid.UUID, PersonRef] = field(default_factory=dict)
    resolved: dict[tuple[str, uuid.UUID], Resolved] = field(default_factory=dict)


def _link_out(link: TodoLink, resolved: dict[tuple[str, uuid.UUID], Resolved]) -> TodoLinkOut:
    target = resolved.get((link.kind, link.target_id), HIDDEN)
    return TodoLinkOut(
        id=link.id,
        kind=link.kind,  # pyright: ignore[reportArgumentType]
        target_id=link.target_id,
        accessible=target.accessible,
        title=target.title if target.accessible else None,
        url=target.url if target.accessible else None,
        detail=target.detail if target.accessible else None,
    )


def _label_out(label: TodoLabel) -> TodoLabelOut:
    return TodoLabelOut(id=label.id, name=label.name, color=label.color)  # pyright: ignore[reportArgumentType]


class TodoService:
    """To-do operations bound to an ``AsyncSession``."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        access: BoardAccess | None = None,
        links: LinkResolver | None = None,
    ) -> None:
        self.session = session
        self.access = access or BoardAccess(session)
        self.links = links or LinkResolver(session, self.access)
        self.outbox: list[TodoMail] = []

    # -- loading and rights -----------------------------------------------------

    async def _actor(self, principal: Principal) -> uuid.UUID:
        me = await self.access.me(principal)
        if me is None:
            raise NotFoundError("account not found")
        return me

    async def _board(self, board_id: uuid.UUID, principal: Principal) -> TodoBoard:
        board = await self.session.get(TodoBoard, board_id)
        if board is None or not await self.access.can_read(board, principal):
            raise NotFoundError(f"board {board_id} not found")
        return board

    async def _configurable(self, board_id: uuid.UUID, principal: Principal) -> TodoBoard:
        board = await self._board(board_id, principal)
        if not await self.access.can_configure(board, principal):
            raise ForbiddenError(
                "Changing this board needs todo.configure.", code="todo_configure_required"
            )
        return board

    async def _card(
        self, card_id: uuid.UUID, principal: Principal, *, lock: bool = False
    ) -> tuple[TodoCard, TodoBoard]:
        """Load a card and its board; ``lock`` locks the board first, then the card.

        Every write locks the board before a card, because a move locks the board
        and then updates the card, and the other order deadlocks with it.
        """
        if lock:
            known = await self.session.get(TodoCard, card_id)
            if known is None:
                raise NotFoundError(f"card {card_id} not found")
            await self._lock_board(known.board_id)
            card = await self.session.scalar(
                select(TodoCard)
                .where(TodoCard.id == card_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        else:
            card = await self.session.get(TodoCard, card_id)
        if card is None:
            raise NotFoundError(f"card {card_id} not found")
        board = await self.session.get(TodoBoard, card.board_id)
        if board is None or not await self.access.can_read(board, principal):
            raise NotFoundError(f"card {card_id} not found")
        return card, board

    async def _lock_board(self, board_id: uuid.UUID) -> None:
        await self.session.execute(
            select(TodoBoard.id).where(TodoBoard.id == board_id).with_for_update()
        )

    @staticmethod
    def _touch(board: TodoBoard) -> None:
        board.updated_at = _now()

    def _event(
        self,
        card: TodoCard,
        kind: str,
        actor: uuid.UUID | None,
        payload: dict[str, JsonValue] | None = None,
    ) -> None:
        # The clock of the process: one request can write several events, and the
        # timeline orders them by this time.
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
        stmt = select(TodoCard).where(
            TodoCard.column_id == column_id, TodoCard.archived_at.is_(None)
        )
        if exclude is not None:
            stmt = stmt.where(TodoCard.id != exclude)
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

    # -- tiles ------------------------------------------------------------------

    async def _facts(self, cards: Sequence[TodoCard], principal: Principal) -> _Facts:
        facts = _Facts()
        if not cards:
            return facts
        ids = [c.id for c in cards]
        for card_id, label_id in (
            await self.session.execute(
                select(TodoCardLabel.card_id, TodoCardLabel.label_id).where(
                    TodoCardLabel.card_id.in_(ids)
                )
            )
        ).all():
            facts.labels.setdefault(card_id, []).append(label_id)
        for card_id, principal_id in (
            await self.session.execute(
                select(TodoAssignee.card_id, TodoAssignee.principal_id).where(
                    TodoAssignee.card_id.in_(ids)
                )
            )
        ).all():
            facts.assignees.setdefault(card_id, []).append(principal_id)
        for card_id, total, done in (
            await self.session.execute(
                select(
                    TodoCheckItem.card_id,
                    func.count(),
                    func.count().filter(TodoCheckItem.done.is_(True)),
                )
                .where(TodoCheckItem.card_id.in_(ids))
                .group_by(TodoCheckItem.card_id)
            )
        ).all():
            facts.checklist[card_id] = (int(done), int(total))
        for card_id, count in (
            await self.session.execute(
                select(TodoComment.card_id, func.count())
                .where(TodoComment.card_id.in_(ids), TodoComment.deleted_at.is_(None))
                .group_by(TodoComment.card_id)
            )
        ).all():
            facts.comments[card_id] = int(count)
        for link in (
            await self.session.scalars(
                select(TodoLink)
                .where(TodoLink.card_id.in_(ids))
                .order_by(TodoLink.created_at, TodoLink.id)
            )
        ).all():
            facts.links.setdefault(link.card_id, []).append(link)
        people = {pid for pids in facts.assignees.values() for pid in pids}
        facts.people = await person_refs(self.session, people)
        primaries = [links[0] for links in facts.links.values() if links]
        facts.resolved = await self.links.resolve(
            [(link.kind, link.target_id) for link in primaries], principal
        )
        return facts

    @staticmethod
    def _tile(card: TodoCard, facts: _Facts) -> TodoCardTile:
        done, total = facts.checklist.get(card.id, (0, 0))
        links = facts.links.get(card.id, [])
        assignees = sorted(
            (facts.people.get(pid, DELETED_PERSON) for pid in facts.assignees.get(card.id, [])),
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
            label_ids=sorted(facts.labels.get(card.id, []), key=str),
            assignees=assignees,
            checklist=ChecklistCount(done=done, total=total),
            comment_count=facts.comments.get(card.id, 0),
            primary_link=_link_out(links[0], facts.resolved) if links else None,
            link_count=len(links),
            version=card.version,
            created_at=card.created_at,
            updated_at=card.updated_at,
        )

    async def tiles(self, cards: Sequence[TodoCard], principal: Principal) -> list[TodoCardTile]:
        """Build the tiles of the cards (in the given order)."""
        facts = await self._facts(cards, principal)
        return [self._tile(c, facts) for c in cards]

    # -- boards -----------------------------------------------------------------

    async def list_boards(
        self, principal: Principal, *, gremium_id: uuid.UUID | None = None
    ) -> list[TodoBoardSummary]:
        """List the readable boards: personal, the gremium boards by name, then team.

        The first call of an account creates its personal board.

        Raises:
            ForbiddenError: A token without ``todo.write`` in its scope (HTTP 403).
        """
        if not principal.scope_allows(TODO_WRITE):
            raise ForbiddenError("The token scope does not allow to-dos.")
        me = await self.access.me(principal)
        if me is not None:
            await ensure_personal_board(self.session, me)
        scope = await self.access.scope(principal)
        stmt = select(TodoBoard).where(scope.condition(), TodoBoard.archived_at.is_(None))
        if gremium_id is not None:
            stmt = stmt.where(TodoBoard.gremium_id == gremium_id)
        boards = list((await self.session.scalars(stmt)).all())
        if not boards:
            return []
        counts = {
            board_id: int(n)
            for board_id, n in (
                await self.session.execute(
                    select(TodoCard.board_id, func.count())
                    .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                    .where(
                        TodoCard.board_id.in_([b.id for b in boards]),
                        TodoCard.archived_at.is_(None),
                        TodoColumn.is_done.is_(False),
                    )
                    .group_by(TodoCard.board_id)
                )
            ).all()
        }
        boards.sort(key=lambda b: (_KIND_ORDER.get(b.kind, 3), b.name.casefold(), str(b.id)))
        return [
            TodoBoardSummary(
                id=b.id,
                name=b.name,
                kind=b.kind,  # pyright: ignore[reportArgumentType]
                gremium_id=b.gremium_id,
                can_write=True,
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
        cards = list(
            (
                await self.session.scalars(
                    select(TodoCard)
                    .where(TodoCard.board_id == board.id, TodoCard.archived_at.is_(None))
                    .order_by(TodoCard.rank, TodoCard.id)
                )
            ).all()
        )
        archived = await self.session.scalar(
            select(func.count())
            .select_from(TodoCard)
            .where(TodoCard.board_id == board.id, TodoCard.archived_at.is_not(None))
        )
        position = {c.id: index for index, c in enumerate(columns)}
        cards.sort(key=lambda c: (position.get(c.column_id, len(columns)), c.rank, str(c.id)))
        per_column: dict[uuid.UUID, int] = {}
        for card in cards:
            per_column[card.column_id] = per_column.get(card.column_id, 0) + 1
        return TodoBoardOut(
            id=board.id,
            name=board.name,
            kind=board.kind,  # pyright: ignore[reportArgumentType]
            gremium_id=board.gremium_id,
            archive_after_days=board.archive_after_days,
            can_write=True,
            can_configure=await self.access.can_configure(board, principal),
            columns=[
                TodoColumnOut(
                    id=c.id,
                    name=c.name,
                    position=c.position,
                    is_done=c.is_done,
                    card_count=per_column.get(c.id, 0),
                )
                for c in columns
            ],
            labels=[_label_out(label) for label in labels],
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
    ) -> Page[TodoCardTile]:
        """Page through the archived cards of a board, newest archive first."""
        board = await self._board(board_id, principal)
        conds = [TodoCard.board_id == board.id, TodoCard.archived_at.is_not(None)]
        term = (q or "").strip()
        if term:
            conds.append(TodoCard.title.ilike(f"%{escape_like(term)}%", escape="\\"))
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

    # -- columns ----------------------------------------------------------------

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
        column = await self.session.get(TodoColumn, column_id)
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
        its column. A card that becomes done writes ``todo_done`` to its linked
        tickets, as a move into the done column does.
        """
        board = await self._configurable(board_id, principal)
        column = await self._column(board, column_id)
        if payload.name is not None:
            column.name = payload.name.strip() or column.name
        if payload.is_done and not column.is_done:
            actor = await self._actor(principal)
            await self._lock_board(board.id)
            now = _now()
            for other in await self._columns(board.id):
                if other.is_done:
                    other.is_done = False
                    for card in await self._all_column_cards(other.id):
                        card.completed_at = None
                        card.updated_at = now
            # The partial unique index allows one done column: clear the old flag
            # before the new one is written.
            await self.session.flush()
            column.is_done = True
            for card in await self._all_column_cards(column.id):
                card.updated_at = now
                if card.completed_at is None:
                    card.completed_at = now
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
        gets ``completed_at`` and writes ``todo_done`` to its linked tickets.

        Raises:
            ConflictError: The done column (``done_column_required``), or cards and no
                ``move_to`` (``column_not_empty``) (HTTP 409).
            ValidationProblem: ``move_to`` is this column or not on the board (HTTP 422).
        """
        board = await self._configurable(board_id, principal)
        column = await self._column(board, column_id)
        if column.is_done:
            raise ConflictError("The done column cannot be deleted.", code="done_column_required")
        await self._lock_board(board.id)
        cards = await self._all_column_cards(column.id)
        if cards:
            if move_to is None:
                raise ConflictError("The column still has cards.", code="column_not_empty")
            target = await self.session.get(TodoColumn, move_to)
            if target is None or target.board_id != board.id or target.id == column.id:
                raise _invalid("moveTo names another column of the board.", "invalid", "moveTo")
            actor = await self._actor(principal)
            live = await self._column_cards(target.id)
            last = live[-1].rank if live else None
            now = _now()
            for card in cards:
                last = between(last, None)
                card.rank = last
                # The same bookkeeping as a move: the event, and on the entry into
                # the done column ``completed_at`` and ``todo_done``.
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
                    await self._write_ticket_done(card, board, actor)
            await self.session.flush()
        await self.session.delete(column)
        await self.session.flush()
        for position, other in enumerate(await self._columns(board.id)):
            other.position = position
        self._touch(board)
        await self.session.commit()
        return await self._board_out(board, principal)

    # -- labels -----------------------------------------------------------------

    async def _label_name_taken(
        self, board_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None
    ) -> bool:
        stmt = select(TodoLabel.id).where(
            TodoLabel.board_id == board_id, func.lower(TodoLabel.name) == name.lower()
        )
        if exclude is not None:
            stmt = stmt.where(TodoLabel.id != exclude)
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

    # -- card detail --------------------------------------------------------------

    async def card(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Return the whole card, archived ones too.

        Raises:
            NotFoundError: The card is unknown or its board not readable (HTTP 404).
        """
        card, board = await self._card(card_id, principal)
        return await self._detail(card, board, principal)

    async def _detail(
        self, card: TodoCard, board: TodoBoard, principal: Principal
    ) -> TodoCardDetail:
        facts = await self._facts([card], principal)
        tile = self._tile(card, facts)
        columns = await self._columns(board.id)
        board_labels = await self._labels(board.id)
        items = list(
            (
                await self.session.scalars(
                    select(TodoCheckItem)
                    .where(TodoCheckItem.card_id == card.id)
                    .order_by(TodoCheckItem.position, TodoCheckItem.id)
                )
            ).all()
        )
        events = list(
            (
                await self.session.scalars(
                    select(TodoEvent)
                    .where(TodoEvent.card_id == card.id)
                    .order_by(TodoEvent.created_at, TodoEvent.id)
                )
            ).all()
        )
        comments = list(
            (
                await self.session.scalars(
                    select(TodoComment)
                    .where(TodoComment.card_id == card.id, TodoComment.deleted_at.is_(None))
                    .order_by(TodoComment.created_at, TodoComment.id)
                )
            ).all()
        )
        links = facts.links.get(card.id, [])
        refs: set[tuple[str, uuid.UUID]] = {(link.kind, link.target_id) for link in links}
        people: set[uuid.UUID | None] = {card.created_by}
        for event in events:
            people.add(event.actor_id)
            if event.kind == "assigned":
                people.add(_uuid_of(event.payload.get("principalId")))
            if event.kind in ("linked", "unlinked"):
                ref = _ref_of(event.payload)
                if ref is not None:
                    refs.add(ref)
        for comment in comments:
            people.add(comment.author_id)
            people.update(_uuid_of(m) for m in comment.mentions or [])
        resolved = await self.links.resolve(refs, principal)
        persons = await person_refs(self.session, people)
        me = await self.access.me(principal)
        own_labels = set(tile.label_ids)
        return TodoCardDetail(
            **tile.model_dump(by_alias=False),
            description_md=card.description_md,
            board_name=board.name,
            board_kind=board.kind,  # pyright: ignore[reportArgumentType]
            can_write=True,
            columns=[TodoColumnRef(id=c.id, name=c.name, is_done=c.is_done) for c in columns],
            labels=[_label_out(label) for label in board_labels if label.id in own_labels],
            board_labels=[_label_out(label) for label in board_labels],
            created_by=persons.get(card.created_by, DELETED_PERSON),
            links=[_link_out(link, resolved) for link in links],
            checklist_items=[
                TodoCheckItemOut(id=i.id, text=i.text, done=i.done, position=i.position)
                for i in items
            ],
            events=[_event_out(e, persons, resolved) for e in events],
            comments=[_comment_out(c, persons, me) for c in comments],
            archived_at=card.archived_at,
        )

    # -- card writes ------------------------------------------------------------

    async def _check_assignees(self, board: TodoBoard, ids: Iterable[uuid.UUID]) -> None:
        wanted = set(ids)
        if wanted and not wanted <= await self.access.member_ids(board):
            raise _invalid(
                "Assignees must be members of the board.", "assignee_not_allowed", "assigneeIds"
            )

    async def create(self, payload: CardCreate, principal: Principal) -> TodoCardDetail:
        """Create a card at the end of its column (default: the first column).

        Raises:
            NotFoundError: The board is unknown or not readable (HTTP 404).
            ValidationProblem: ``column_not_on_board``, ``assignee_not_allowed``,
                ``label_not_on_board`` or ``link_target_not_found`` (HTTP 422).
        """
        actor = await self._actor(principal)
        board = await self._board(payload.board_id, principal)
        await self._lock_board(board.id)
        columns = await self._columns(board.id)
        if payload.column_id is None:
            column = columns[0]
        else:
            matches = [c for c in columns if c.id == payload.column_id]
            if not matches:
                raise _invalid(
                    "The column is not on this board.", "column_not_on_board", "columnId"
                )
            column = matches[0]
        assignees = list(dict.fromkeys(payload.assignee_ids))
        await self._check_assignees(board, assignees)
        label_ids = list(dict.fromkeys(payload.label_ids))
        if label_ids and not set(label_ids) <= {label.id for label in await self._labels(board.id)}:
            raise _invalid("A label is not on this board.", "label_not_on_board", "labelIds")
        links = list(dict.fromkeys((link.kind, link.target_id) for link in payload.links))
        for kind, target_id in links:
            if not await self.links.readable(kind, target_id, principal):
                raise _invalid("The link target was not found.", "link_target_not_found", "links")
        live = await self._column_cards(column.id)
        now = _now()
        card = TodoCard(
            id=uuid.uuid4(),
            board_id=board.id,
            column_id=column.id,
            rank=between(live[-1].rank if live else None, None),
            title=payload.title.strip() or payload.title,
            description_md=payload.description_md,
            due_date=payload.due_date,
            created_by=actor,
            completed_at=now if column.is_done else None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(card)
        await self.session.flush()
        for principal_id in assignees:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=principal_id))
        for label_id in label_ids:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
        for kind, target_id in links:
            self.session.add(_new_link(card.id, kind, target_id, actor))
        self._event(card, "created", actor)
        await self.session.flush()
        if column.is_done:
            await self._write_ticket_done(card, board, actor)
        self._touch(board)
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
        card, board = await self._card(card_id, principal, lock=True)
        if payload.version != card.version:
            raise ConflictError(
                "The card was changed in the meantime.", code="card_version_conflict"
            )
        fields = payload.model_fields_set
        changed = False
        if payload.title is not None:
            title = payload.title.strip() or payload.title
            if title != card.title:
                self._event(card, "renamed", actor, {"from": card.title, "to": title})
                card.title = title
                changed = True
        if "description_md" in fields and payload.description_md != card.description_md:
            card.description_md = payload.description_md
            changed = True
        if "due_date" in fields and payload.due_date != card.due_date:
            self._event(
                card,
                "due",
                actor,
                {"from": _iso_date(card.due_date), "to": _iso_date(payload.due_date)},
            )
            card.due_date = payload.due_date
            changed = True
        if changed:
            card.version += 1
            card.updated_at = _now()
            self._touch(board)
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
            ValidationProblem: ``column_not_on_board``, or ``rank_neighbors_invalid``
                for a neighbor outside the column or two neighbors that are not
                adjacent (HTTP 422).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
        await self._lock_board(board.id)
        # A parallel move of the same card held the lock: read the card again, so the
        # column change below works from the committed column.
        await self.session.refresh(card)
        columns = {c.id: c for c in await self._columns(board.id)}
        target = columns.get(payload.column_id)
        if target is None:
            raise _invalid("The column is not on this board.", "column_not_on_board", "columnId")
        siblings = await self._column_cards(target.id, exclude=card.id)
        index = _slot(siblings, payload.after_id, payload.before_id)
        low = siblings[index - 1].rank if index > 0 else None
        high = siblings[index].rank if index < len(siblings) else None
        try:
            card.rank = between(low, high)
        except RankError:
            # Two cards share a rank (or a rank is broken): give the column a fresh order.
            ordered = [*siblings[:index], card, *siblings[index:]]
            for sibling, rank in zip(ordered, spread(len(ordered)), strict=True):
                sibling.rank = rank
                sibling.updated_at = _now()
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
        self._touch(board)
        await self.session.commit()
        return (await self.tiles([card], principal))[0]

    async def complete(self, card: TodoCard, board: TodoBoard, actor: uuid.UUID) -> bool:
        """Move an open card to the end of the done column, without a commit.

        Returns:
            True when the card moved (False: no done column, or done already).
        """
        # The board lock orders this rank against a parallel move or create, and the
        # card is read again after the lock.
        await self._lock_board(board.id)
        await self.session.refresh(card)
        columns = await self._columns(board.id)
        done = next((c for c in columns if c.is_done), None)
        if done is None or card.column_id == done.id:
            return False
        source = next((c for c in columns if c.id == card.column_id), None)
        live = await self._column_cards(done.id, exclude=card.id)
        card.rank = between(live[-1].rank if live else None, None)
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
        self._touch(board)
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
        card, board = await self._card(card_id, principal)
        if card.archived_at is None:
            card.archived_at = card.updated_at = _now()
            self._event(card, "archived", actor)
            self._touch(board)
            await self.session.commit()

    async def restore_card(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Bring an archived card back into its column.

        A card in the done column gets a new ``completed_at``, else the archive cron
        archives it again at its next run.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
        if card.archived_at is not None:
            # Read the column before the card changes. A read after them autoflushes
            # the card, so ``completed_at`` goes in a second UPDATE without an explicit
            # ``updated_at``; its ``onupdate=now()`` then expires the attribute.
            column = await self.session.get(TodoColumn, card.column_id)
            card.archived_at = None
            card.updated_at = _now()
            if column is not None and column.is_done:
                card.completed_at = card.updated_at
            self._event(card, "restored", actor)
            self._touch(board)
            await self.session.commit()
        return await self._detail(card, board, principal)

    # -- assignees and labels -----------------------------------------------------

    async def add_assignee(
        self, card_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Assign a member of the board (422 ``assignee_not_allowed`` otherwise).

        The board lock makes a parallel identical request wait and then see the row.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True)
        await self._check_assignees(board, [principal_id])
        present = await self.session.scalar(
            select(TodoAssignee.principal_id).where(
                TodoAssignee.card_id == card.id, TodoAssignee.principal_id == principal_id
            )
        )
        if present is None:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=principal_id))
            self._event(card, "assigned", actor, {"principalId": str(principal_id), "added": True})
            self._touch(board)
            await self.session.commit()
            self._mail("assigned", card, [principal_id], actor)
        return await self._detail(card, board, principal)

    async def remove_assignee(
        self, card_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Remove an assignee; an unknown one changes nothing."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
        result = await self.session.execute(
            delete(TodoAssignee).where(
                TodoAssignee.card_id == card.id, TodoAssignee.principal_id == principal_id
            )
        )
        if getattr(result, "rowcount", 0):
            self._event(card, "assigned", actor, {"principalId": str(principal_id), "added": False})
            self._touch(board)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_card_label(
        self, card_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Put a label of the board on the card (422 ``label_not_on_board`` otherwise)."""
        card, board = await self._card(card_id, principal, lock=True)
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
            self._touch(board)
            await self.session.commit()
        return await self._detail(card, board, principal)

    async def remove_card_label(
        self, card_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Take a label off the card."""
        card, board = await self._card(card_id, principal)
        await self.session.execute(
            delete(TodoCardLabel).where(
                TodoCardLabel.card_id == card.id, TodoCardLabel.label_id == label_id
            )
        )
        self._touch(board)
        await self.session.commit()
        return await self._detail(card, board, principal)

    # -- checklist --------------------------------------------------------------

    async def add_check_item(
        self, card_id: uuid.UUID, text: str, principal: Principal
    ) -> TodoCardDetail:
        """Append a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
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
        self._touch(board)
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
        card, board = await self._card(card_id, principal)
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
            others.insert(min(payload.position, len(others)), item)
            for position, entry in enumerate(others):
                entry.position = position
        self._touch(board)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def delete_check_item(
        self, card_id: uuid.UUID, item_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Delete a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
        item = await self._check_item(card, item_id)
        await self.session.delete(item)
        self._event(card, "checklist", actor, {"action": "removed", "text": item.text})
        self._touch(board)
        await self.session.commit()
        return await self._detail(card, board, principal)

    # -- links ------------------------------------------------------------------

    async def add_link(
        self, card_id: uuid.UUID, kind: str, target_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Link the card to a target that the caller reads.

        Raises:
            ValidationProblem: ``link_self`` or ``link_target_not_found`` (HTTP 422).
            ConflictError: The link exists (HTTP 409, ``link_exists``).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True)
        if kind == "todo" and target_id == card.id:
            raise _invalid("A card cannot link to itself.", "link_self", "targetId")
        if not await self.links.readable(kind, target_id, principal):
            raise _invalid("The link target was not found.", "link_target_not_found", "targetId")
        column = getattr(TodoLink, LINK_COLUMNS[kind])
        present = await self.session.scalar(
            select(TodoLink.id).where(TodoLink.card_id == card.id, column == target_id)
        )
        if present is not None:
            raise ConflictError("The card has this link.", code="link_exists")
        self.session.add(_new_link(card.id, kind, target_id, actor))
        self._event(card, "linked", actor, {"linkKind": kind, "targetId": str(target_id)})
        self._touch(board)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def remove_link(
        self, card_id: uuid.UUID, link_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Remove a link of the card."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
        link = await self.session.get(TodoLink, link_id)
        if link is None or link.card_id != card.id:
            raise NotFoundError(f"link {link_id} not found")
        payload: dict[str, JsonValue] = {"linkKind": link.kind, "targetId": str(link.target_id)}
        await self.session.delete(link)
        self._event(card, "unlinked", actor, payload)
        self._touch(board)
        await self.session.commit()
        return await self._detail(card, board, principal)

    # -- comments ---------------------------------------------------------------

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
    ) -> TodoCommentOut:
        """Add a comment; new mentions get the mail ``todo_mentioned``."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal)
        wanted = list(dict.fromkeys(mentions))
        await self._check_mentions(board, wanted)
        comment = TodoComment(
            id=uuid.uuid4(),
            card_id=card.id,
            author_id=actor,
            body=body,
            mentions=[str(m) for m in wanted],
            created_at=_now(),
        )
        self.session.add(comment)
        self._touch(board)
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
        card, board = await self._card(card_id, principal)
        comment, me = await self._own_comment(card, comment_id, principal)
        wanted = list(dict.fromkeys(mentions))
        await self._check_mentions(board, wanted)
        before = {_uuid_of(m) for m in comment.mentions or []}
        comment.body = body
        comment.mentions = [str(m) for m in wanted]
        comment.edited_at = _now()
        self._touch(board)
        await self.session.commit()
        self._mail("mentioned", card, [m for m in wanted if m not in before], me, _excerpt(body))
        return await self._comment(comment, me)

    async def delete_comment(
        self, card_id: uuid.UUID, comment_id: uuid.UUID, principal: Principal
    ) -> None:
        """Soft-delete an own comment."""
        card, board = await self._card(card_id, principal)
        comment, _me = await self._own_comment(card, comment_id, principal)
        comment.deleted_at = _now()
        self._touch(board)
        await self.session.commit()

    async def _comment(self, comment: TodoComment, me: uuid.UUID) -> TodoCommentOut:
        people: set[uuid.UUID | None] = {comment.author_id}
        people.update(_uuid_of(m) for m in comment.mentions or [])
        persons = await person_refs(self.session, people)
        return _comment_out(comment, persons, me)

    # -- across boards ------------------------------------------------------------

    async def mine(self, principal: Principal) -> TodoMine:
        """The open cards assigned to the caller over every readable board.

        ``dueSoonCount`` counts the ones due within 7 days (overdue included).

        Raises:
            ForbiddenError: A token without ``todo.write`` in its scope (HTTP 403).
        """
        if not principal.scope_allows(TODO_WRITE):
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
        items = []
        for card, board, column in rows:
            tile = self._tile(card, facts)
            items.append(
                TodoMineItem(
                    **tile.model_dump(by_alias=False),
                    board_name=board.name,
                    board_kind=board.kind,  # pyright: ignore[reportArgumentType]
                    column_name=column.name,
                    labels=[_label_out(labels[i]) for i in tile.label_ids if i in labels],
                )
            )
        due_soon = sum(1 for c in cards if c.due_date is not None and c.due_date <= limit)
        return TodoMine(items=items, due_soon_count=due_soon)

    async def linked(
        self, kind: str, target_id: uuid.UUID, principal: Principal
    ) -> list[TodoLinkedCard]:
        """The readable live cards that link to a target: open first, then by due date."""
        if not principal.scope_allows(TODO_WRITE):
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
        out = [
            TodoLinkedCard(
                id=card.id,
                board_id=board.id,
                board_name=board.name,
                title=card.title,
                column_name=col.name,
                is_done=col.is_done,
                due_date=card.due_date,
                assignees=self._tile(card, facts).assignees,
            )
            for card, board, col in rows
        ]
        out.sort(key=lambda c: (c.is_done, c.due_date is None, c.due_date or date.max, c.title))
        return out

    async def search(
        self, q: str, principal: Principal, *, limit: int
    ) -> list[tuple[TodoCard, TodoBoard, TodoColumn]]:
        """Find live cards by title on the boards that the principal reads (palette)."""
        if not principal.scope_allows(TODO_WRITE):
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

    # -- agenda coupling ----------------------------------------------------------

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
        card, board = await self._card(card_id, principal, lock=True)
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
            self._touch(board)


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


def _new_link(card_id: uuid.UUID, kind: str, target_id: uuid.UUID, actor: uuid.UUID) -> TodoLink:
    link = TodoLink(id=uuid.uuid4(), card_id=card_id, created_by=actor, created_at=_now())
    setattr(link, LINK_COLUMNS[kind], target_id)
    return link


def _uuid_of(value: Any) -> uuid.UUID | None:
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


def _person(persons: dict[uuid.UUID, PersonRef], principal_id: uuid.UUID | None) -> PersonRef:
    if principal_id is None:
        return DELETED_PERSON
    return persons.get(principal_id, DELETED_PERSON)


def _event_out(
    event: TodoEvent,
    persons: dict[uuid.UUID, PersonRef],
    resolved: dict[tuple[str, uuid.UUID], Resolved],
) -> TodoEventOut:
    payload: dict[str, JsonValue] = dict(event.payload or {})
    if event.kind == "assigned":
        person = _person(persons, _uuid_of(payload.pop("principalId", None)))
        payload = {
            "person": person.model_dump(by_alias=True, mode="json"),
            "added": bool(payload.get("added", False)),
        }
    elif event.kind in ("linked", "unlinked"):
        ref = _ref_of(payload)
        target = resolved.get(ref, HIDDEN) if ref is not None else HIDDEN
        payload["title"] = target.title if target.accessible else None
    return TodoEventOut(
        id=event.id,
        kind=event.kind,  # pyright: ignore[reportArgumentType]
        actor=_person(persons, event.actor_id) if event.actor_id is not None else None,
        at=event.created_at,
        payload=payload,
    )


def _comment_out(
    comment: TodoComment, persons: dict[uuid.UUID, PersonRef], me: uuid.UUID | None
) -> TodoCommentOut:
    return TodoCommentOut(
        id=comment.id,
        author=_person(persons, comment.author_id),
        body=comment.body,
        mentions=[_person(persons, _uuid_of(m)) for m in comment.mentions or []],
        at=comment.created_at,
        edited_at=comment.edited_at,
        is_own=me is not None and comment.author_id == me,
    )


__all__ = ["BERLIN", "TodoMail", "TodoService", "berlin_today"]
