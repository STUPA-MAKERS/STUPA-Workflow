"""Reads across boards: the own cards, the board rows, linked cards and the search sources."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import func, select

from app.modules.auth.principal import Principal
from app.modules.todos.access import ReadScope, token_reads
from app.modules.todos.boards import ensure_personal_board
from app.modules.todos.grouping import grouped
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoLabel,
)
from app.modules.todos.schemas import TodoAssignedBoard, TodoLinkedCard, TodoMine
from app.modules.todos.service.base import TodoServiceBase
from app.modules.todos.service.common import (
    DUE_SOON_DAYS,
    _board_order,
    _in_column_order,
    berlin_today,
)
from app.modules.todos.service.rows import _assigned_board, _mine_item, _tile
from app.shared.errors import ForbiddenError
from app.shared.search import dialect_of, trigram_rank


class ReadOps(TodoServiceBase):
    """Cross-board reads."""

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
                gremium_id=await self.access.gremium_of(b),
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

    async def linked_cards(
        self, card_ids: Sequence[uuid.UUID], principal: Principal
    ) -> dict[uuid.UUID, TodoLinkedCard]:
        """The readable live cards of ``card_ids`` with their board, column and Event.

        A linked Event carries its dates, its place and its balance (spec 000489).
        """
        if not card_ids or not token_reads(principal):
            return {}
        scope = await self.access.scope(principal)
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard, TodoColumn)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .where(
                    TodoCard.id.in_(list(card_ids)),
                    TodoCard.archived_at.is_(None),
                    scope.condition(),
                )
            )
        ).all()
        if not rows:
            return {}
        facts = await self._facts([card for card, _b, _c in rows], principal)
        return {
            card.id: TodoLinkedCard(
                id=card.id,
                board_id=board.id,
                board_name=board.name,
                title=card.title,
                column_name=col.name,
                is_done=col.is_done,
                due_date=card.due_date,
                assignees=_tile(card, facts).assignees,
            )
            for card, board, col in rows
        }

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
