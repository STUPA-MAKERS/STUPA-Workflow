"""Integration: the files of an agenda item (TOP), on real Postgres.

* A writer of the meeting uploads, lists and removes a file; the agenda counts it.
* The download follows the read rule of the meeting: a stranger gets 404.
* The window is the window of the item text: a final protocol gives 409, and a live
  meeting with a protokollant takes files only from the protokollant (403).
* Removing the item, deleting the meeting and deleting the Gremium remove the
  objects with the rows.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.admin.service import ConfigService
from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from tests._support.memory_storage import MemoryStorage, wire_storage
from tests.integration.modules.livevote.conftest import admin, audit_actions, seed

pytestmark = pytest.mark.integration

_PDF = b"%PDF-1.4\n%agenda\n"


def _upload(client: TestClient, meeting_id: uuid.UUID, item_id: uuid.UUID) -> Any:
    return client.post(
        f"/api/meetings/{meeting_id}/agenda/{item_id}/attachments",
        files={"file": ("Haushalt Entwurf.pdf", _PDF, "application/pdf")},
    )


async def _mark_clean(maker: async_sessionmaker[AsyncSession], attachment_id: str) -> None:
    async with maker() as session:
        await session.execute(
            update(Attachment)
            .where(Attachment.id == uuid.UUID(attachment_id))
            .values(scanned=True, scan_result="clean")
        )
        await session.commit()


async def test_a_writer_uploads_lists_downloads_and_removes_a_file(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="planned", items=2)
    storage = MemoryStorage()
    wire_storage(api, storage)
    base = f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[0]}/attachments"
    with TestClient(api) as client:
        created = _upload(client, s.meeting_id, s.item_ids[0])
        assert created.status_code == 201, created.text
        file = created.json()
        assert (file["filename"], file["mime"], file["scanned"]) == (
            "Haushalt Entwurf.pdf",
            "application/pdf",
            False,
        )
        assert [f["id"] for f in client.get(base).json()] == [file["id"]]
        agenda = client.get(f"/api/meetings/{s.meeting_id}/agenda").json()
        assert [i["attachmentCount"] for i in agenda] == [1, 0]
        other = f"/api/meetings/{s.meeting_id}/agenda/{s.item_ids[1]}/attachments"
        assert client.get(other).json() == []
        assert client.get(f"/api/attachments/{file['id']}").status_code == 409

        await _mark_clean(maker, file["id"])
        down = client.get(f"/api/attachments/{file['id']}/download")
        assert down.status_code == 200 and down.content == _PDF

        api.dependency_overrides[get_current_principal] = lambda: Principal(
            sub="stranger", roles=[], permissions=set()
        )
        assert client.get(f"/api/attachments/{file['id']}/download").status_code == 404
        assert client.get(base).status_code == 403
        assert _upload(client, s.meeting_id, s.item_ids[0]).status_code == 403
        api.dependency_overrides[get_current_principal] = admin

        assert client.delete(f"{other}/{file['id']}").status_code == 404
        assert client.delete(f"{base}/{file['id']}").status_code == 204
        assert client.get(base).json() == []
    assert storage.blobs == {}
    actions = [e.action for e in await audit_actions(maker, target_id=uuid.UUID(file["id"]))]
    assert actions == ["attachment_upload", "attachment_delete"]


async def test_a_final_protocol_locks_the_files(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="closed", items=1, protocol="final")
    wire_storage(api, MemoryStorage())
    with TestClient(api) as client:
        resp = _upload(client, s.meeting_id, s.item_ids[0])
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "protocol_locked"


async def test_a_live_meeting_takes_files_from_the_protokollant_only(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    s = await seed(maker, status="live", items=1, protocol="draft")
    wire_storage(api, MemoryStorage())
    with TestClient(api) as client:
        resp = _upload(client, s.meeting_id, s.item_ids[0])
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "not_protokollant"


async def test_item_meeting_and_gremium_deletes_remove_the_objects(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    first = await seed(maker, status="planned", items=2)
    second = await seed(maker, status="planned", items=1)
    third = await seed(maker, status="planned", items=1)
    storage = MemoryStorage()
    wire_storage(api, storage)
    with TestClient(api) as client:
        for s in (first, second, third):
            assert _upload(client, s.meeting_id, s.item_ids[0]).status_code == 201
        assert _upload(client, first.meeting_id, first.item_ids[1]).status_code == 201
        assert len(storage.blobs) == 4

        removed = client.delete(f"/api/meetings/{first.meeting_id}/agenda/{first.item_ids[0]}")
        assert removed.status_code == 200, removed.text
        assert len(storage.blobs) == 3
        assert client.delete(f"/api/meetings/{first.meeting_id}").status_code == 204
        assert len(storage.blobs) == 2
        assert client.delete(f"/api/meetings/{second.meeting_id}").status_code == 204
        assert len(storage.blobs) == 1
    async with maker() as session:
        await ConfigService(session, storage=storage).delete_gremium(third.gremium_id, admin())
    assert storage.blobs == {}
    async with maker() as session:
        assert (await session.scalars(select(Attachment.id))).all() == []
