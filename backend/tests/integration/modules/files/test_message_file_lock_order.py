"""Integration: a file removal and an infected scan verdict do not deadlock (real Postgres).

``finalize_scan`` of an infected file updates its row first (row lock) and then
writes the quarantine audit entry, which takes the advisory lock of the audit chain.
A removal that wrote an audit entry before it locked the file rows held the chain
lock and waited on the row, so Postgres aborted one of the two transactions. Every
removal now locks the file rows before its first audit entry: the Gremium delete,
the delete of an application comment, the erasure of a personal board and a
message with two files.

Each test holds the row lock of a scan, starts the removal, waits until the removal
waits on a lock, and then lets the scan write its audit entry and commit. Both
transactions must finish. The scanned file has the higher id, so the removal reaches
it second.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import Gremium
from app.modules.admin.service import ConfigService
from app.modules.applications.models import Comment
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.privacy.service import PrincipalService
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.todos.boards import ensure_gremium_board, ensure_personal_board
from app.modules.todos.models import TodoBoard, TodoCard, TodoColumn, TodoComment
from tests._support.guest_apps import create_guest_application, seed_guest_flow
from tests._support.memory_storage import MemoryStorage
from tests.integration.conftest import clear_privacy_tables

pytestmark = pytest.mark.integration

_SLUG = "lockorder-"


def _clear(eng: Engine) -> None:
    clear_privacy_tables(eng)
    with eng.begin() as conn:
        conn.execute(text(f"DELETE FROM gremium WHERE slug LIKE '{_SLUG}%'"))


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    _clear(engine)
    eng = create_async_engine(migrated[1])
    try:
        yield async_sessionmaker(eng, expire_on_commit=False)
    finally:
        await eng.dispose()
        _clear(engine)


def _low_id() -> uuid.UUID:
    return uuid.UUID(int=uuid.uuid4().int >> 8)


def _high_id() -> uuid.UUID:
    return uuid.UUID(int=uuid.uuid4().int | (0xFF << 120))


def _files(**owner: uuid.UUID) -> tuple[Attachment, Attachment]:
    """Two files of one owner; the second one gets the scan verdict."""
    return tuple(  # pyright: ignore[reportReturnType]
        Attachment(
            id=attachment_id,
            filename=f"{attachment_id}.pdf",
            mime="application/pdf",
            size=4,
            storage_key=f"files/{attachment_id}.pdf",
            scanned=False,
            **owner,
        )
        for attachment_id in (_low_id(), _high_id())
    )


async def _wait_for_a_lock_wait(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as probe:
        for _ in range(200):
            waiting = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            if waiting:
                return
            await asyncio.sleep(0.05)
    pytest.fail("the removal never waited on the row lock of the scan")


async def _race(
    maker: async_sessionmaker[AsyncSession],
    scanned_id: uuid.UUID,
    remove: Callable[[AsyncSession], Awaitable[object]],
) -> None:
    """Hold the row lock of an infected verdict while the removal runs, then audit."""

    async def _removal() -> None:
        async with maker() as session:
            await remove(session)

    async with maker() as scan:
        row = await scan.get(Attachment, scanned_id)
        assert row is not None
        row.scanned = True
        row.scan_result = "Eicar-Test-Signature"
        row.storage_key = None
        await scan.flush()
        task = asyncio.create_task(_removal())
        try:
            await _wait_for_a_lock_wait(maker)
            await audit_record(
                scan,
                actor="system",
                action=AuditAction.ATTACHMENT_QUARANTINE,
                target_type="attachment",
                target_id=str(scanned_id),
                data={"signature": "Eicar-Test-Signature"},
            )
            await scan.commit()
        except BaseException:
            task.cancel()
            raise
    await asyncio.wait_for(task, timeout=20)


async def _assert_removed(
    maker: async_sessionmaker[AsyncSession], files: tuple[Attachment, Attachment]
) -> None:
    async with maker() as session:
        for attachment in files:
            assert await session.get(Attachment, attachment.id) is None
        actions = set(
            (
                await session.scalars(
                    select(AuditEntry.action).where(AuditEntry.target_id == str(files[1].id))
                )
            ).all()
        )
    assert actions == {"attachment_quarantine", "attachment_delete"}


async def _person(session: AsyncSession) -> PrincipalRow:
    row = PrincipalRow(sub=f"p-{uuid.uuid4().hex[:8]}", display_name="P", email="p@example.org")
    session.add(row)
    await session.flush()
    return row


async def _comment_on(
    session: AsyncSession, board_id: uuid.UUID, author_id: uuid.UUID
) -> uuid.UUID:
    column = await session.scalar(select(TodoColumn.id).where(TodoColumn.board_id == board_id))
    assert column is not None
    card = TodoCard(
        id=uuid.uuid4(),
        board_id=board_id,
        column_id=column,
        rank="m",
        title="K",
        created_by=author_id,
    )
    session.add(card)
    await session.flush()
    comment = TodoComment(id=uuid.uuid4(), card_id=card.id, author_id=author_id, body="b")
    session.add(comment)
    await session.flush()
    return comment.id


async def test_a_gremium_delete_and_an_infected_verdict_both_finish(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        gremium = Gremium(name="G", slug=f"{_SLUG}{uuid.uuid4().hex[:8]}")
        session.add(gremium)
        await session.flush()
        await ensure_gremium_board(session, gremium.id, "G")
        board = await session.scalar(select(TodoBoard.id).where(TodoBoard.gremium_id == gremium.id))
        assert board is not None
        author = await _person(session)
        files = _files(todo_comment_id=await _comment_on(session, board, author.id))
        session.add_all(files)
        await session.commit()
        gremium_id = gremium.id
    admin = Principal(sub="gremien-admin", permissions={"admin.gremien"})

    async def _remove(session: AsyncSession) -> None:
        await ConfigService(session, storage=MemoryStorage()).delete_gremium(gremium_id, admin)

    await _race(maker, files[1].id, _remove)
    await _assert_removed(maker, files)


async def test_an_application_comment_delete_and_an_infected_verdict_both_finish(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    app_id = await create_guest_application(maker, await seed_guest_flow(maker))
    async with maker() as session:
        comment = Comment(
            application_id=app_id, author_kind="applicant", body="", visibility="public"
        )
        session.add(comment)
        await session.flush()
        files = _files(comment_id=comment.id)
        session.add_all(files)
        await session.commit()
        comment_id = comment.id

    async def _remove(session: AsyncSession) -> None:
        await ApplicationsService(session).delete_comment(
            app_id,
            comment_id,
            actor="admin",
            viewer_sub="admin",
            viewer_is_applicant=False,
            can_manage=True,
            files=FilesService(session),
        )

    await _race(maker, files[1].id, _remove)
    await _assert_removed(maker, files)


async def test_a_principal_erasure_and_an_infected_verdict_both_finish(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        owner = await _person(session)
        await ensure_personal_board(session, owner.id)
        board = await session.scalar(
            select(TodoBoard.id).where(TodoBoard.kind == "personal", TodoBoard.owner_id == owner.id)
        )
        assert board is not None
        files = _files(todo_comment_id=await _comment_on(session, board, owner.id))
        session.add_all(files)
        await session.commit()
        owner_id = owner.id

    async def _remove(session: AsyncSession) -> None:
        await PrincipalService(session).erase(
            owner_id,
            actor="dpo",
            files=FilesService(session, storage=MemoryStorage()),  # pyright: ignore[reportArgumentType]
        )

    await _race(maker, files[1].id, _remove)
    await _assert_removed(maker, files)


async def test_a_note_with_two_files_and_an_infected_verdict_both_finish(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        author = await _person(session)
        ticket = Ticket(kind="bug", title="T", body="b", reporter_principal_id=author.id)
        session.add(ticket)
        await session.flush()
        note = TicketNote(ticket_id=ticket.id, author_id=author.id, body="n")
        session.add(note)
        await session.flush()
        files = _files(ticket_note_id=note.id)
        session.add_all(files)
        await session.commit()
        note_id = note.id

    async def _remove(session: AsyncSession) -> None:
        removed = await FilesService(session).delete_for_messages(
            "ticket_note", [note_id], actor="admin"
        )
        assert removed == 2
        await session.commit()

    await _race(maker, files[1].id, _remove)
    await _assert_removed(maker, files)
