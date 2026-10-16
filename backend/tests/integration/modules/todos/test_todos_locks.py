"""Integration: every to-do write locks the board before the card (real Postgres).

A move locks the board and then updates the card. A write that locks the card first
and then updates the board deadlocks with it. Each test holds the board lock the way
a move does, starts the other write, then updates the card and commits.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.todos.schemas import CardCreate, CardPatch
from app.modules.todos.service import TodoService
from tests.integration.modules.todos.conftest import add_person
from tests.integration.modules.todos.test_todos_lifecycle import _personal
from worker.todos import archive_done_todos

pytestmark = pytest.mark.integration


async def _as_a_move(
    maker: async_sessionmaker[AsyncSession],
    board_id: uuid.UUID,
    card_id: uuid.UUID,
    write: asyncio.Task[Any],
) -> Any:
    async with maker() as mover:
        await mover.execute(
            text("SELECT id FROM todo_board WHERE id = :b FOR UPDATE"), {"b": board_id}
        )
        await asyncio.sleep(0.3)
        assert not write.done()
        await mover.execute(text("UPDATE todo_card SET rank = rank WHERE id = :c"), {"c": card_id})
        await mover.commit()
    return await asyncio.wait_for(write, 10)


async def test_a_card_edit_waits_for_a_move(maker: async_sessionmaker[AsyncSession]) -> None:
    me, me_id = await add_person(maker, "Ada")
    board, _columns = await _personal(maker, me_id)
    async with maker() as session:
        payload = CardCreate.model_validate({"boardId": str(board.id), "title": "Alt"})
        card_id = (await TodoService(session).create(payload, me)).id

    async def edit() -> str:
        async with maker() as session:
            patch = CardPatch(version=1, title="Neu")
            return (await TodoService(session).patch(card_id, patch, me)).title

    assert await _as_a_move(maker, board.id, card_id, asyncio.create_task(edit())) == "Neu"


async def test_the_archive_cron_waits_for_a_move(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    me, me_id = await add_person(maker, "Ada")
    board, columns = await _personal(maker, me_id)
    async with maker() as session:
        payload = CardCreate.model_validate(
            {"boardId": str(board.id), "title": "Fertig", "columnId": str(columns[-1].id)}
        )
        card_id = (await TodoService(session).create(payload, me)).id
        await session.execute(
            text("UPDATE todo_card SET completed_at = now() - interval '31 days' WHERE id = :c"),
            {"c": card_id},
        )
        await session.commit()
    cron = asyncio.create_task(archive_done_todos({"todos_sessionmaker": maker}))
    assert await _as_a_move(maker, board.id, card_id, cron) == 1
