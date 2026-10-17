"""Create boards with their default columns.

The migration backfills a board for every gremium and the team board "Plattform".
At runtime ``ensure_gremium_board`` runs in the transaction of the gremium create,
and ``ensure_personal_board`` creates the board "Meine To-Dos" of an account on its
first ``GET /todos/boards``. The insert of a personal board skips a conflict on
``uq_todo_board_owner``, so two parallel first reads create one board.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.todos.models import DEFAULT_COLUMNS, PERSONAL_BOARD_NAME, TodoBoard, TodoColumn


def add_default_columns(session: AsyncSession, board_id: uuid.UUID) -> None:
    """Add Offen, In Arbeit, Wartet and Erledigt (the done column) to a board."""
    last = len(DEFAULT_COLUMNS) - 1
    for position, name in enumerate(DEFAULT_COLUMNS):
        session.add(
            TodoColumn(
                id=uuid.uuid4(),
                board_id=board_id,
                name=name,
                position=position,
                is_done=position == last,
            )
        )


async def ensure_gremium_board(session: AsyncSession, gremium_id: uuid.UUID, name: str) -> bool:
    """Create the board of a gremium when it has none. The caller commits.

    Returns:
        True when the call created the board.
    """
    existing = await session.scalar(select(TodoBoard.id).where(TodoBoard.gremium_id == gremium_id))
    if existing is not None:
        return False
    board = TodoBoard(id=uuid.uuid4(), name=name, kind="gremium", gremium_id=gremium_id)
    session.add(board)
    await session.flush()
    add_default_columns(session, board.id)
    await session.flush()
    return True


async def ensure_personal_board(session: AsyncSession, owner_id: uuid.UUID) -> bool:
    """Create the personal board of an account when it has none, and commit.

    Returns:
        True when the call created the board.
    """
    existing = await session.scalar(select(TodoBoard.id).where(TodoBoard.owner_id == owner_id))
    if existing is not None:
        return False
    board_id = uuid.uuid4()
    created = await session.scalar(
        insert(TodoBoard)
        .values(id=board_id, name=PERSONAL_BOARD_NAME, kind="personal", owner_id=owner_id)
        .on_conflict_do_nothing(
            index_elements=["owner_id"], index_where=text("owner_id IS NOT NULL")
        )
        .returning(TodoBoard.id)
    )
    if created is None:
        return False
    add_default_columns(session, board_id)
    await session.commit()
    return True
