"""The to-do part of the erasure and of the Auskunft.

``erase_todos`` removes the assignments of the person and deletes the personal
board with its cards, because that board holds only the person's own notes. Cards,
comments and events on the shared boards stay: their author, actor and creator ids
point to the erased principal, which shows as "Gelöschte Person".

``todo_export`` collects the cards that the person created or is assigned to, and
the person's own comments, for the Auskunft workbook.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoComment,
)


async def erase_todos(session: AsyncSession, principal_id: UUID) -> None:
    """Remove the assignments and the personal board of the principal."""
    await session.execute(delete(TodoAssignee).where(TodoAssignee.principal_id == principal_id))
    await session.execute(
        delete(TodoBoard).where(TodoBoard.kind == "personal", TodoBoard.owner_id == principal_id)
    )


async def todo_export(session: AsyncSession, principal_ids: list[UUID]) -> dict[str, Any]:
    """Collect the cards and the comments of the principals for the Auskunft.

    A deleted comment is still stored, so it is part of the export with its
    ``deletedAt``.

    Returns:
        ``{"cards": [...], "comments": [...]}``, ready for the workbook.
    """
    if not principal_ids:
        return {"cards": [], "comments": []}
    assigned = select(TodoAssignee.card_id).where(TodoAssignee.principal_id.in_(principal_ids))
    card_rows = (
        await session.execute(
            select(TodoCard, TodoBoard.name, TodoColumn.name)
            .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
            .join(TodoColumn, TodoColumn.id == TodoCard.column_id)
            .where(or_(TodoCard.created_by.in_(principal_ids), TodoCard.id.in_(assigned)))
            .order_by(TodoCard.created_at, TodoCard.id)
        )
    ).all()
    cards = [
        {
            "board": board_name,
            "title": card.title,
            "column": column_name,
            "dueDate": card.due_date,
            "createdAt": card.created_at,
        }
        for card, board_name, column_name in card_rows
    ]
    comment_rows = (
        await session.execute(
            select(TodoComment, TodoCard.title)
            .join(TodoCard, TodoCard.id == TodoComment.card_id)
            .where(TodoComment.author_id.in_(principal_ids))
            .order_by(TodoComment.created_at, TodoComment.id)
        )
    ).all()
    comments = [
        {
            "card": card_title,
            "body": comment.body,
            "createdAt": comment.created_at,
            "deletedAt": comment.deleted_at,
        }
        for comment, card_title in comment_rows
    ]
    return {"cards": cards, "comments": comments}
