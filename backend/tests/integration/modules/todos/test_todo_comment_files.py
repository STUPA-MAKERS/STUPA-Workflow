"""Integration: the files of a to-do comment (real Postgres).

A comment binds its drafts, the card detail lists them, a reader of the board
downloads them and anybody else gets 404. Deleting the comment, and the erasure of
the owner of a personal board, remove the files with their objects. The erasure
removes the objects only after its commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.files.drafts import hash_draft_token
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.todos.models import TodoComment
from app.modules.todos.privacy import erase_todos
from app.settings import Settings
from tests._support.memory_storage import MemoryStorage, wire_storage
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


async def _draft(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage: MemoryStorage,
    token: str,
    name: str,
) -> uuid.UUID:
    draft_id = uuid.uuid4()
    key = f"drafts/{draft_id}/{name}"
    await storage.put(key, b"bytes", "application/pdf")
    async with maker() as session:
        session.add(
            Attachment(
                id=draft_id,
                filename=name,
                mime="application/pdf",
                size=5,
                storage_key=key,
                scanned=True,
                scan_result="clean",
                draft_token_hash=hash_draft_token(token, settings.magic_link_secret),
                draft_expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.commit()
    return draft_id


async def test_a_comment_binds_its_files_and_the_board_gates_the_download(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Bind the files to a comment and let the board gate the download.

    The lifespan sets the storage of the services, and the test replaces it. For someone who
    is not a member of the gremium, the file does not exist. Signed out, the download gives
    401. A comment marked deleted hides its remaining files.
    """
    member, member_id = await add_person(maker, "Max")
    stranger, _ = await add_person(maker, "Sam")
    gremium_id, board_id = await add_gremium(maker)
    await add_member(maker, gremium_id, member_id, "todo.write")
    storage = MemoryStorage()
    wire_storage(api.app, storage)
    first = await _draft(maker, settings, storage, "tok", "a.pdf")
    second = await _draft(maker, settings, storage, "tok", "b.pdf")
    api.login(member)
    with TestClient(api.app) as client:
        api.app.state.object_storage = storage
        card = _ok(
            client.post("/api/todos/cards", json={"boardId": str(board_id), "title": "A"}), 201
        )
        comment = _ok(
            client.post(
                f"/api/todos/cards/{card['id']}/comments",
                json={"body": "", "attachmentIds": [str(first)], "draftToken": "tok"},
            ),
            201,
        )
        assert [(a["filename"], a["scanState"]) for a in comment["attachments"]] == [
            ("a.pdf", "clean")
        ]
        other = _ok(
            client.post(
                f"/api/todos/cards/{card['id']}/comments",
                json={"body": "zwei", "attachmentIds": [str(second)], "draftToken": "tok"},
            ),
            201,
        )
        detail = _ok(client.get(f"/api/todos/cards/{card['id']}"))
        assert [[a["id"] for a in c["attachments"]] for c in detail["comments"]] == [
            [str(first)],
            [str(second)],
        ]
        assert _ok(client.get(f"/api/attachments/{first}"))["url"].endswith("/download")
        down = client.get(f"/api/attachments/{first}/download")
        assert down.status_code == 200 and down.content == b"bytes"
        foreign = client.post(
            f"/api/todos/cards/{card['id']}/comments",
            json={"body": "x", "attachmentIds": [str(first)], "draftToken": "tok"},
        )
        assert foreign.status_code == 422
        assert foreign.json()["code"] == "draft_attachments_missing"

        api.login(stranger)
        assert client.get(f"/api/attachments/{first}/download").status_code == 404
        assert client.get(f"/api/attachments/{first}").status_code == 404
        api.login(None)
        assert client.get(f"/api/attachments/{first}/download").status_code == 401

        api.login(member)
        _ok(client.delete(f"/api/todos/cards/{card['id']}/comments/{comment['id']}"), 204)
        assert client.get(f"/api/attachments/{first}").status_code == 404
    assert f"drafts/{first}/a.pdf" not in storage.blobs
    async with maker() as session:
        assert await session.get(Attachment, first) is None
        await session.execute(
            update(TodoComment)
            .where(TodoComment.id == uuid.UUID(other["id"]))
            .values(deleted_at=datetime.now(UTC))
        )
        await session.commit()
    with TestClient(api.app) as client:
        assert client.get(f"/api/attachments/{second}").status_code == 404


async def test_the_erasure_of_a_personal_board_removes_the_comment_files(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Remove the comment files when a personal board is erased.

    The objects stay until the commit, so a rollback keeps every file whole.
    """
    me, me_id = await add_person(maker, "Ada")
    storage = MemoryStorage()
    draft = await _draft(maker, settings, storage, "tok", "privat.pdf")
    api.login(me)
    with TestClient(api.app) as client:
        (board,) = _ok(client.get("/api/todos/boards"))
        card = _ok(
            client.post("/api/todos/cards", json={"boardId": board["id"], "title": "A"}), 201
        )
        _ok(
            client.post(
                f"/api/todos/cards/{card['id']}/comments",
                json={"body": "x", "attachmentIds": [str(draft)], "draftToken": "tok"},
            ),
            201,
        )
    async with maker() as session:
        files = FilesService(session, storage=storage, settings=settings)
        await erase_todos(session, me_id, files=files, actor="dpo")
        assert storage.blobs != {}
        await session.rollback()
    async with maker() as session:
        row = await session.get(Attachment, draft)
        assert row is not None and row.storage_key in storage.blobs
    async with maker() as session:
        files = FilesService(session, storage=storage, settings=settings)
        keys = await erase_todos(session, me_id, files=files, actor="dpo")
        await session.commit()
        await files.remove_objects(keys)
        assert await session.get(Attachment, draft) is None
    assert storage.blobs == {}
