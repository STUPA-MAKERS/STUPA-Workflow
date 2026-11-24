"""The to-do entries of the Kalender: card events and due cards."""

from __future__ import annotations

from datetime import date

from sqlalchemy import exists, func, select

from app.modules.auth.principal import Principal
from app.modules.todos.access import token_reads
from app.modules.todos.models import TodoAssignee, TodoBoard, TodoCard, TodoCardEvent, TodoColumn
from app.modules.todos.service.base import TodoServiceBase


class CalendarOps(TodoServiceBase):
    """Calendar reads."""

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
