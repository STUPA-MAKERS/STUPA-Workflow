"""Integration: the to-dos across their life (real Postgres).

Covers the archive cron and the due reminder against the SQL, the erasure of an
account, the Auskunft rows, the account merge (mentions, assignments, the personal
board) and the migration: backfill, grants, and downgrade.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.principal_merge import PrincipalMergeService
from app.modules.privacy.service import AuskunftService, PrincipalService
from app.modules.todos.boards import ensure_personal_board
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoColumn,
    TodoComment,
    TodoEvent,
)
from app.modules.todos.schemas import CardCreate
from app.modules.todos.service import BERLIN, TodoService
from app.settings import Settings
from tests.integration.modules.todos.conftest import add_person
from worker.todos import archive_done_todos, process_todo_due

pytestmark = pytest.mark.integration


class _Queue:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []

    async def enqueue(self, *args: Any, **kw: Any) -> None:
        self.jobs.append({"args": args, **kw})


async def _personal(
    maker: async_sessionmaker[AsyncSession], owner: uuid.UUID
) -> tuple[TodoBoard, list[TodoColumn]]:
    async with maker() as session:
        await ensure_personal_board(session, owner)
        board = await session.scalar(select(TodoBoard).where(TodoBoard.owner_id == owner))
        assert board is not None
        columns = list(
            (
                await session.scalars(
                    select(TodoColumn)
                    .where(TodoColumn.board_id == board.id)
                    .order_by(TodoColumn.position)
                )
            ).all()
        )
        return board, columns


async def _create(
    maker: async_sessionmaker[AsyncSession], principal: Any, board_id: uuid.UUID, **kw: Any
) -> uuid.UUID:
    async with maker() as session:
        payload = CardCreate.model_validate({"boardId": str(board_id), "title": "Karte", **kw})
        return (await TodoService(session).create(payload, principal)).id


async def test_the_archive_cron(maker: async_sessionmaker[AsyncSession]) -> None:
    me, me_id = await add_person(maker, "Ada")
    board, columns = await _personal(maker, me_id)
    done = columns[-1]
    old = await _create(maker, me, board.id, columnId=str(done.id))
    fresh = await _create(maker, me, board.id, columnId=str(done.id))
    open_card = await _create(maker, me, board.id)
    async with maker() as session:
        await session.execute(
            text(
                "UPDATE todo_card SET completed_at = now() - interval '31 days' "
                "WHERE id IN (:a, :b)"
            ),
            {"a": old, "b": open_card},
        )
        await session.commit()
    ctx = {"todos_sessionmaker": maker}
    assert await archive_done_todos(ctx) == 1
    assert await archive_done_todos(ctx) == 0
    async with maker() as session:
        rows = {c.id: c for c in (await session.scalars(select(TodoCard))).all()}
        events = (
            await session.scalars(select(TodoEvent).where(TodoEvent.kind == "archived"))
        ).all()
    assert rows[old].archived_at is not None
    assert rows[fresh].archived_at is None and rows[open_card].archived_at is None
    assert [(e.card_id, e.actor_id) for e in events] == [(old, None)]
    # A board without a limit never archives.
    async with maker() as session:
        await session.execute(text("UPDATE todo_board SET archive_after_days = NULL"))
        await session.execute(
            text("UPDATE todo_card SET completed_at = now() - interval '400 days' WHERE id = :f"),
            {"f": fresh},
        )
        await session.commit()
    assert await archive_done_todos(ctx) == 0


async def test_the_due_reminder(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    me, me_id = await add_person(maker, "Ada")
    board, columns = await _personal(maker, me_id)
    now = datetime(2026, 10, 1, 8, tzinfo=BERLIN).astimezone(UTC)
    tomorrow = (now.astimezone(BERLIN) + timedelta(days=1)).date()
    due = await _create(maker, me, board.id, dueDate=str(tomorrow), assigneeIds=[str(me_id)])
    await _create(
        maker,
        me,
        board.id,
        dueDate=str(tomorrow),
        columnId=str(columns[-1].id),
        assigneeIds=[str(me_id)],
    )
    await _create(
        maker, me, board.id, dueDate=str(tomorrow + timedelta(days=1)), assigneeIds=[str(me_id)]
    )
    queue = _Queue()
    ctx = {"todos_sessionmaker": maker, "mail_queue": queue, "settings": settings}
    assert await process_todo_due(ctx, now) == 1
    assert await process_todo_due(ctx, now) == 0
    assert len(queue.jobs) == 1
    async with maker() as session:
        card = await session.get(TodoCard, due)
        assert card is not None and card.due_reminded_on == tomorrow


async def test_erasure_and_auskunft(maker: async_sessionmaker[AsyncSession]) -> None:
    me, me_id = await add_person(maker, "Ada")
    other, other_id = await add_person(maker, "Otto")
    mine, _ = await _personal(maker, me_id)
    theirs, _ = await _personal(maker, other_id)
    await _create(maker, me, mine.id, title="Privat")
    async with maker() as session:
        await session.execute(
            text("UPDATE principal SET email = :e WHERE id = :i"),
            {"e": "ada@example.org", "i": me_id},
        )
        await session.commit()
    # Otto's board does not accept Ada; write the assignment and a comment directly.
    shared = await _create(maker, other, theirs.id, title="Gemeinsam")
    async with maker() as session:
        session.add(TodoAssignee(card_id=shared, principal_id=me_id))
        session.add(TodoComment(card_id=shared, author_id=me_id, body="Meins", mentions=[]))
        await session.commit()
        data = await AuskunftService(session).collect("ada@example.org")
    assert {c["title"] for c in data["todos"]} == {"Privat", "Gemeinsam"}
    assert [c["body"] for c in data["todo_comments"]] == ["Meins"]
    async with maker() as session:
        await PrincipalService(session).erase(me_id, actor="admin")
    async with maker() as session:
        assert await session.scalar(select(TodoBoard).where(TodoBoard.owner_id == me_id)) is None
        assert (
            await session.scalars(select(TodoAssignee).where(TodoAssignee.principal_id == me_id))
        ).all() == []
        kept = await session.scalar(select(TodoComment).where(TodoComment.author_id == me_id))
        assert kept is not None


async def test_the_account_merge(maker: async_sessionmaker[AsyncSession]) -> None:
    old, old_id = await add_person(maker, "Alt")
    new, new_id = await add_person(maker, "Neu")
    third, third_id = await add_person(maker, "Dritt")
    old_board, old_columns = await _personal(maker, old_id)
    new_board, new_columns = await _personal(maker, new_id)
    third_board, _ = await _personal(maker, third_id)
    moving = await _create(maker, old, old_board.id, title="Offen")
    finished = await _create(
        maker, old, old_board.id, title="Fertig", columnId=str(old_columns[-1].id)
    )
    present = await _create(maker, new, new_board.id, title="Da")
    shared = await _create(maker, third, third_board.id, title="Geteilt")
    async with maker() as session:
        session.add_all(
            [
                TodoAssignee(card_id=shared, principal_id=old_id),
                TodoAssignee(card_id=shared, principal_id=new_id),
                TodoComment(
                    card_id=shared,
                    author_id=third_id,
                    body="@alt",
                    mentions=[str(old_id), str(third_id)],
                ),
            ]
        )
        await session.commit()
    async with maker() as session:
        preview = await PrincipalMergeService(session).preview(old_id, new_id, actor="merge-admin")
    todos = next(a for a in preview.areas if a.area == "todos")
    assert todos.combined == 2  # one assignment, one board
    async with maker() as session:
        await PrincipalMergeService(session).merge(old_id, new_id, actor="merge-admin")
    async with maker() as session:
        boards = (
            await session.scalars(select(TodoBoard).where(TodoBoard.kind == "personal"))
        ).all()
        assert {b.owner_id for b in boards} == {new_id, third_id}
        cards = {c.id: c for c in (await session.scalars(select(TodoCard))).all()}
        assert (
            cards[moving].board_id == new_board.id and cards[moving].column_id == new_columns[0].id
        )
        assert cards[finished].column_id == new_columns[-1].id
        assert cards[moving].created_by == new_id
        assert cards[moving].rank > cards[present].rank
        assignees = (
            await session.scalars(
                select(TodoAssignee.principal_id).where(TodoAssignee.card_id == shared)
            )
        ).all()
        assert assignees == [new_id]
        note = await session.scalar(select(TodoComment).where(TodoComment.card_id == shared))
        assert note is not None and sorted(note.mentions) == sorted([str(new_id), str(third_id)])


async def test_the_account_merge_moves_a_lone_board(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    _old, old_id = await add_person(maker, "Alt")
    _new, new_id = await add_person(maker, "Neu")
    board, _ = await _personal(maker, old_id)
    async with maker() as session:
        await PrincipalMergeService(session).merge(old_id, new_id, actor="merge-admin")
    async with maker() as session:
        row = await session.get(TodoBoard, board.id)
        assert row is not None and row.owner_id == new_id


def test_the_migration_backfills_and_downgrades(alembic_cfg: Config, engine: Engine) -> None:
    command.downgrade(alembic_cfg, "86718c748401")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT to_regclass('todo_board')")).scalar_one() is None
        gid = conn.execute(
            text("INSERT INTO gremium (name, slug) VALUES ('Todo-G', 'todo-mig') RETURNING id")
        ).scalar_one()
        for key in ("member", "vorstand"):
            conn.execute(
                text(
                    "INSERT INTO gremium_role (gremium_id, key, permissions) "
                    "VALUES (:g, :k, '[\"vote.cast\"]'::jsonb)"
                ),
                {"g": gid, "k": key},
            )
    try:
        command.upgrade(alembic_cfg, "head")
        with engine.connect() as conn:
            boards = conn.execute(
                text("SELECT kind, name, gremium_id, permission FROM todo_board ORDER BY kind")
            ).all()
            columns = conn.execute(
                text(
                    "SELECT c.name, c.is_done FROM todo_column c "
                    "JOIN todo_board b ON b.id = c.board_id "
                    "WHERE b.gremium_id = :g ORDER BY c.position"
                ),
                {"g": gid},
            ).all()
            perms = dict(
                conn.execute(
                    text("SELECT key, permissions FROM gremium_role WHERE gremium_id = :g"),
                    {"g": gid},
                ).all()
            )
        assert ("gremium", "Todo-G", gid, None) in boards
        assert any(b[0] == "team" and b[3] is not None for b in boards)
        assert [tuple(c) for c in columns] == [
            ("Offen", False),
            ("In Arbeit", False),
            ("Wartet", False),
            ("Erledigt", True),
        ]
        assert "todo.write" in perms["member"] and "todo.configure" not in perms["member"]
        assert {"todo.write", "todo.configure"} <= set(perms["vorstand"])
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM gremium WHERE slug = 'todo-mig'"))
