"""The to-do side of a ticket: ``TicketTodoHooks`` for the ticket service.

``open_count`` counts the linked cards that are open (not in a done column, not
archived) on a board that the viewer reads. ``complete`` moves those cards into the
done column of their board, each with its ``moved`` event and the ``todo_done``
event on the ticket; a card on a board that the actor reads but cannot write
(``todo.read_all``) stays. It takes the board locks in board-id order, because two
closes that lock the same boards in different orders deadlock.
``readable_cards`` tells which cards of ``todo_done`` events the viewer may see by
title. With a ``broker``, ``complete`` publishes the pings of the moved cards after its
commit (``live``).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.livevote.broker import PatternBroker
from app.modules.todos.live import publish_pings
from app.modules.todos.models import TodoBoard, TodoCard, TodoColumn, TodoLink
from app.modules.todos.service import TodoService


class TicketTodoBridge:
    """``TicketTodoHooks`` over the todos tables."""

    def __init__(
        self,
        session: AsyncSession,
        service: TodoService | None = None,
        *,
        broker: PatternBroker | None = None,
    ) -> None:
        """Bind the bridge to a session, the to-do service and the ping broker."""
        self.session = session
        self.todos = service or TodoService(session)
        self.broker = broker

    async def _open_cards(
        self, ticket_id: uuid.UUID, principal: Principal
    ) -> list[tuple[TodoCard, TodoBoard]]:
        rows = (
            await self.session.execute(
                select(TodoCard, TodoBoard)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
                .join(TodoLink, TodoLink.card_id == TodoCard.id)
                .where(
                    TodoLink.ticket_id == ticket_id,
                    TodoCard.archived_at.is_(None),
                    TodoColumn.is_done.is_(False),
                )
                .order_by(TodoCard.created_at, TodoCard.id)
            )
        ).all()
        return [
            (card, board)
            for card, board in rows
            if await self.todos.access.can_read(board, principal)
        ]

    async def open_count(self, ticket_id: uuid.UUID, principal: Principal) -> int:
        """Count the open linked cards that the principal can read."""
        return len(await self._open_cards(ticket_id, principal))

    async def complete(self, ticket_id: uuid.UUID, principal: Principal) -> None:
        """Move the open linked cards that the principal can write into done.

        One transaction locks every board of the loop. The order by board id (the order
        of the archive cron) keeps two closes on the same boards apart, and the stable
        sort keeps the creation order of the cards of one board.
        """
        cards = [
            (card, board)
            for card, board in await self._open_cards(ticket_id, principal)
            if await self.todos.access.can_write(board, principal)
        ]
        actor = await self.todos.access.me(principal)
        if not cards or actor is None:
            return
        moved = False
        for card, board in sorted(cards, key=lambda pair: pair[1].id):
            moved = await self.todos.complete(card, board, actor) or moved
        if moved:
            await self.session.commit()
            if self.broker is not None:
                await publish_pings(self.broker, self.todos.pings.drain())

    async def readable_cards(
        self, card_ids: Iterable[uuid.UUID], principal: Principal
    ) -> set[uuid.UUID]:
        """Return the cards among ``card_ids`` whose board the principal reads."""
        wanted = set(card_ids)
        if not wanted:
            return set()
        rows = (
            await self.session.execute(
                select(TodoCard.id, TodoBoard)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .where(TodoCard.id.in_(wanted))
            )
        ).all()
        return {
            card_id for card_id, board in rows if await self.todos.access.can_read(board, principal)
        }
