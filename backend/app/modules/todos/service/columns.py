"""The columns and the labels of a board."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.modules.auth.principal import Principal
from app.modules.todos.models import TodoBoard, TodoColumn, TodoLabel
from app.modules.todos.schemas import (
    ColumnPatch,
    LabelCreate,
    LabelPatch,
    TodoBoardOut,
    TodoLabelOut,
)
from app.modules.todos.service.base import TodoServiceBase
from app.modules.todos.service.common import _invalid, _now
from app.modules.todos.service.ranks import _append
from app.modules.todos.service.rows import _label_out
from app.shared.errors import ConflictError, NotFoundError


class ColumnOps(TodoServiceBase):
    """Column and label writes."""

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
