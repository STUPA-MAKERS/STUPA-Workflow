"""The to-do entries of the Kalender: the due cards."""

from __future__ import annotations

from datetime import date

from sqlalchemy import exists, select

from app.modules.auth.principal import Principal
from app.modules.todos.access import token_reads
from app.modules.todos.models import TodoAssignee, TodoBoard, TodoCard, TodoColumn
from app.modules.todos.service.base import TodoServiceBase


class CalendarOps(TodoServiceBase):
    """Calendar reads."""

    async def calendar_due_cards(self, principal: Principal) -> list[tuple[TodoCard, TodoBoard]]:
        """The open cards with a due date assigned to the principal (spec 000549).

        Only boards that the principal reads count. A done or archived card and a card on an
        archived board stay out.
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
                    .where(
                        TodoAssignee.principal_id == me,
                        TodoCard.due_date.is_not(None),
                        TodoCard.archived_at.is_(None),
                        TodoColumn.is_done.is_(False),
                        TodoBoard.archived_at.is_(None),
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
        archived card and a card on an archived board stay out, as in `calendar_due_cards`.

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
                    .where(
                        TodoCard.due_date.is_not(None),
                        TodoCard.archived_at.is_(None),
                        TodoColumn.is_done.is_(False),
                        TodoBoard.archived_at.is_(None),
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
