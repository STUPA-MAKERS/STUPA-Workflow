"""Integration: every to-do write locks the board before the card (real Postgres).

A move locks the board and then updates the card. A write that locks the card first
and then updates the board deadlocks with it. Each test holds the board lock the way
a move does, starts the other write, then updates the card and commits.

The agenda path locks the board before the meeting, because a card create locks the
board and then inserts a meeting link. ``completeTodos`` locks the boards in id
order, so two closes on the same two boards wait for each other.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.todos.schemas import CardCreate, CardPatch
from app.modules.todos.service import TodoService
from tests.integration.modules.todos.conftest import add_gremium, add_person
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


async def test_the_agenda_path_locks_the_board_before_the_meeting(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    from datetime import date, timedelta

    from app.modules.livevote.agenda_service import AgendaService
    from app.modules.livevote.models import Meeting

    gid, bid = await add_gremium(maker)
    admin, admin_id = await add_person(maker, "Admin")
    lead = Principal(sub=admin.sub, roles=["admin"])
    async with maker() as session:
        meeting = Meeting(
            gremium_id=gid, title="GV", date=date.today() + timedelta(days=3), status="planned"
        )
        session.add(meeting)
        payload = CardCreate.model_validate({"boardId": str(bid), "title": "Haushalt"})
        await session.commit()
        card_id = (await TodoService(session).create(payload, lead)).id

    async def add_to_agenda() -> str | None:
        async with maker() as session:
            todos = TodoService(session)
            card = await todos.card_for_agenda(card_id, gid, lead)
            item = await AgendaService(session).add_todo_in_tx(
                meeting.id, todo_id=card.id, title=card.title, actor=lead.sub
            )
            await todos.link_agenda_item(card, item.id, lead)
            await session.commit()
            return item.title

    async with maker() as creator:
        # A card create: the board lock, then a link that references the meeting.
        await creator.execute(
            text("SELECT id FROM todo_board WHERE id = :b FOR UPDATE"), {"b": bid}
        )
        agenda = asyncio.create_task(add_to_agenda())
        await asyncio.sleep(0.3)
        assert not agenda.done()
        await creator.execute(
            text(
                "INSERT INTO todo_link (id, card_id, meeting_id, created_by) "
                "VALUES (:i, :c, :m, :p)"
            ),
            {"i": uuid.uuid4(), "c": card_id, "m": meeting.id, "p": admin_id},
        )
        await creator.execute(
            text("UPDATE todo_board SET updated_at = now() WHERE id = :b"), {"b": bid}
        )
        await creator.commit()
    assert await asyncio.wait_for(agenda, 10) == "Haushalt"


async def test_two_ticket_closes_lock_the_boards_in_one_order(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    from app.modules.tickets.models import Ticket
    from app.modules.todos.hooks import TicketTodoBridge
    from app.modules.todos.models import TodoLink

    admin, admin_id = await add_person(maker, "Admin")
    lead = Principal(sub=admin.sub, roles=["admin"])
    _, first_board = await add_gremium(maker, "StuPa")
    _, second_board = await add_gremium(maker, "AStA")
    low, high = sorted([first_board, second_board])
    tickets: list[uuid.UUID] = []
    async with maker() as session:
        for _ in range(2):
            ticket = Ticket(kind="bug", title="T", body="b", reporter_principal_id=admin_id)
            session.add(ticket)
            await session.flush()
            tickets.append(ticket.id)
        await session.commit()
        # Ticket 1 has its older card on the high board, ticket 2 on the low board.
        for ticket_id, boards in ((tickets[0], (high, low)), (tickets[1], (low, high))):
            for board_id in boards:
                payload = CardCreate.model_validate({"boardId": str(board_id), "title": "K"})
                created = await TodoService(session).create(payload, lead)
                session.add(TodoLink(card_id=created.id, ticket_id=ticket_id, created_by=admin_id))
                await session.commit()

    async def close(ticket_id: uuid.UUID) -> None:
        async with maker() as session:
            await TicketTodoBridge(session).complete(ticket_id, lead)

    async with maker() as holder:
        # Both closes wait for the low board, so neither holds the high one yet.
        await holder.execute(text("SELECT id FROM todo_board WHERE id = :b FOR UPDATE"), {"b": low})
        closes = [asyncio.create_task(close(t)) for t in tickets]
        await asyncio.sleep(0.3)
        assert not any(task.done() for task in closes)
        await holder.execute(
            text("SELECT id FROM todo_board WHERE id = :b FOR UPDATE NOWAIT"), {"b": high}
        )
        await holder.commit()
    await asyncio.wait_for(asyncio.gather(*closes), 10)
    async with maker() as session:
        done = (
            await session.execute(
                text(
                    "SELECT count(*) FROM todo_card c JOIN todo_column col "
                    "ON col.id = c.column_id WHERE col.is_done"
                )
            )
        ).scalar_one()
        assert done == 4
