"""The to-do part of the erasure and of the Auskunft.

``erase_todos`` removes the assignments of the person and deletes the personal
board with its cards, because that board holds only the person's own notes. The file
rows of the comments on that board go first, because the board cascade would leave
their objects behind. The objects go only after the caller commits, because a
rollback brings the rows back and a row without its object is a broken download. The
board and its cards are locked before the comment ids are read, so a comment that
binds files at the same moment is part of the ids or fails on the deleted card.
``lock_personal_todos`` takes these locks and the locks of the file rows, so the
erasure can take them before its first audit entry.
Cards, comments, their files and events on the shared boards stay: their author,
actor and creator ids point to the erased principal, which shows as "Gelöschte
Person".

``todo_export`` collects the cards that the person created or is assigned to, and
the person's own comments with the names of their files, for the Auskunft workbook.
The description of a card is part of it only when the person created the card,
because the description is the creator's text.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoComment,
)


async def lock_personal_todos(
    session: AsyncSession, principal_id: UUID, *, files: FilesService | None = None
) -> list[UUID]:
    """Lock the personal board of the principal, its cards and the comment files.

    The board goes first and then its cards, the order of every to-do write. The card
    lock is ``FOR UPDATE``, which waits for the key-share lock of a comment insert. A
    comment that binds files therefore commits before the ids are read, or its insert
    waits and then fails on the deleted card. Otherwise its files would lose their row
    through the board cascade and keep their object.

    The file rows of the comments are locked last. The erasure calls this function
    before its first audit entry, because ``finalize_scan`` of an infected file locks
    its row first and then waits for the lock of the audit chain
    (``FilesService.lock_for_messages``).

    Returns:
        The ids of the comments on the personal board, for ``erase_todos``.
    """
    boards = select(TodoBoard.id).where(
        TodoBoard.kind == "personal", TodoBoard.owner_id == principal_id
    )
    await session.execute(boards.order_by(TodoBoard.id).with_for_update())
    await session.execute(
        select(TodoCard.id)
        .where(TodoCard.board_id.in_(boards))
        .order_by(TodoCard.id)
        .with_for_update()
    )
    comment_ids = list(
        (
            await session.scalars(
                select(TodoComment.id)
                .join(TodoCard, TodoCard.id == TodoComment.card_id)
                .where(TodoCard.board_id.in_(boards))
                .order_by(TodoComment.id)
            )
        ).all()
    )
    await (files or FilesService(session)).lock_for_messages("todo_comment", comment_ids)
    return comment_ids


async def erase_todos(
    session: AsyncSession,
    principal_id: UUID,
    *,
    files: FilesService | None = None,
    actor: str = "system",
    comment_ids: list[UUID] | None = None,
) -> list[str]:
    """Remove the assignments and the personal board of the principal, without a commit.

    The files of the comments on the personal board go first: rows and audit entries
    (``drop_for_messages``). The caller commits and then passes the returned keys to
    ``FilesService.remove_objects``.

    ``comment_ids`` comes from ``lock_personal_todos``, which a caller with earlier
    audit entries runs before the first of them. Without it, the function takes the
    locks itself.

    Returns:
        The storage keys of the removed comment files.
    """
    files = files or FilesService(session)
    if comment_ids is None:
        comment_ids = await lock_personal_todos(session, principal_id, files=files)
    storage_keys = await files.drop_for_messages("todo_comment", comment_ids, actor=actor)
    await session.execute(delete(TodoAssignee).where(TodoAssignee.principal_id == principal_id))
    await session.execute(
        delete(TodoBoard).where(TodoBoard.kind == "personal", TodoBoard.owner_id == principal_id)
    )
    return storage_keys


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
            "description": card.description_md if card.created_by in principal_ids else None,
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
    names = await _file_names([comment.id for comment, _title in comment_rows], session)
    comments = [
        {
            "card": card_title,
            "body": comment.body,
            "createdAt": comment.created_at,
            "deletedAt": comment.deleted_at,
            "attachments": names.get(comment.id, []),
        }
        for comment, card_title in comment_rows
    ]
    return {"cards": cards, "comments": comments}


async def _file_names(ids: list[UUID], session: AsyncSession) -> dict[UUID, list[str]]:
    """Return the file names of the comments, oldest first."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Attachment.todo_comment_id, Attachment.filename)
            .where(Attachment.todo_comment_id.in_(ids))
            .order_by(Attachment.created_at, Attachment.id)
        )
    ).all()
    out: dict[UUID, list[str]] = {}
    for comment_id, filename in rows:
        out.setdefault(cast(UUID, comment_id), []).append(filename)
    return out
