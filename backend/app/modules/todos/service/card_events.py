"""The event of a card (Termin), its follow-up and series, and the boards that take one."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.modules.auth.principal import Principal
from app.modules.todos import events as todo_events
from app.modules.todos import link_store
from app.modules.todos.models import (
    TodoCard,
    TodoCardEvent,
    TodoCardLabel,
    TodoCheckItem,
    TodoEventSeries,
)
from app.modules.todos.schemas import EventIn, TodoCardDetail, TodoEventRef, TodoEventSeriesOut
from app.modules.todos.service.common import _invalid, _now
from app.modules.todos.service.details import DetailOps
from app.modules.todos.service.ranks import _append
from app.modules.todos.service.rows import _event_fields, _event_row
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError
from app.shared.search import escape_like


class EventOps(DetailOps):
    """Event writes on a card."""

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
            refs = [edge.target for edge in await link_store.edges(self.session, "todo", [card.id])]
            await todo_events.check_one_event(self.session, card.id, refs)
            self.session.add(_event_row(card.id, payload))
        else:
            for name, value in _event_fields(payload).items():
                setattr(row, name, value)
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
                start_time=row.start_time,
                end_time=row.end_time,
            )
            for card, row in rows
        ]
