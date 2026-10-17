"""The to-do part of the account merge (``admin/principal_merge.py``).

A person has at most one personal board (``uq_todo_board_owner``). When both
accounts have one, ``fold_personal_board`` moves the cards of the source board into
the board of the target and deletes the source board: a card in the done column goes
to the done column, every other card to the first column, each at the end of its new
column. A label moves with its cards; when the target board has a label of the same
name (case-insensitive), the cards take that label instead.

``rewrite_mentions`` replaces the id of the source in the ``mentions`` list of every
comment, so a mention follows the merge like the author does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.todos.lexorank import between
from app.modules.todos.models import (
    TodoBoard,
    TodoCard,
    TodoCardLabel,
    TodoColumn,
    TodoLabel,
)


async def _targets(session: AsyncSession, board_id: UUID) -> tuple[UUID, UUID]:
    """Return the first column and the done column of a board."""
    columns = (
        await session.scalars(
            select(TodoColumn)
            .where(TodoColumn.board_id == board_id)
            .order_by(TodoColumn.position, TodoColumn.id)
        )
    ).all()
    done = next(c.id for c in columns if c.is_done)
    return columns[0].id, done


async def _fold_labels(session: AsyncSession, source_id: UUID, target_id: UUID) -> None:
    target = {
        label.name.lower(): label.id
        for label in (
            await session.scalars(select(TodoLabel).where(TodoLabel.board_id == target_id))
        ).all()
    }
    for label in (
        await session.scalars(select(TodoLabel).where(TodoLabel.board_id == source_id))
    ).all():
        same = target.get(label.name.lower())
        if same is None:
            label.board_id = target_id
            continue
        await session.execute(
            update(TodoCardLabel)
            .where(TodoCardLabel.label_id == label.id)
            .values(label_id=same)
            .execution_options(synchronize_session=False)
        )
        await session.delete(label)
    await session.flush()


async def fold_personal_board(session: AsyncSession, source_id: UUID, target_id: UUID) -> int:
    """Move every card of the board ``source_id`` into ``target_id``, then delete it.

    Returns:
        The number of moved cards.
    """
    first, done = await _targets(session, target_id)
    await _fold_labels(session, source_id, target_id)
    cards = (
        await session.execute(
            select(TodoCard, TodoColumn.is_done)
            .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
            .where(TodoCard.board_id == source_id)
            .order_by(TodoColumn.position, TodoCard.rank, TodoCard.id)
        )
    ).all()
    last: dict[UUID, str | None] = {}
    for column_id in (first, done):
        last[column_id] = await session.scalar(
            select(func.max(TodoCard.rank)).where(TodoCard.column_id == column_id)
        )
    for card, is_done in cards:
        column_id = done if is_done else first
        rank = between(last[column_id], None)
        last[column_id] = rank
        card.board_id = target_id
        card.column_id = column_id
        card.rank = rank
    await session.flush()
    await session.execute(
        update(TodoBoard)
        .where(TodoBoard.id == target_id)
        .values(updated_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        delete(TodoBoard)
        .where(TodoBoard.id == source_id)
        .execution_options(synchronize_session=False)
    )
    return len(cards)


_MENTIONS = (
    "UPDATE todo_comment SET mentions = ("
    " SELECT coalesce(jsonb_agg(DISTINCT CASE WHEN m = CAST(:old AS text)"
    " THEN CAST(:new AS text) ELSE m END), '[]'::jsonb)"
    " FROM jsonb_array_elements_text(mentions) AS m"
    ") WHERE mentions @> jsonb_build_array(CAST(:old AS text))"
)
_MENTION_COUNT = (
    "SELECT count(*) FROM todo_comment WHERE mentions @> jsonb_build_array(CAST(:old AS text))"
)


async def rewrite_mentions(session: AsyncSession, old: UUID, new: UUID, *, apply: bool) -> int:
    """Replace ``old`` by ``new`` in the mentions of every comment.

    Returns:
        The number of comments that mention ``old``.
    """
    if not apply:
        return int(await session.scalar(text(_MENTION_COUNT).bindparams(old=str(old))) or 0)
    result = await session.execute(text(_MENTIONS).bindparams(old=str(old), new=str(new)))
    return cast("CursorResult[Any]", result).rowcount
