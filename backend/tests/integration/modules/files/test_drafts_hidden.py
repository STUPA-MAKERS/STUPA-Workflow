"""Integration: no application-scoped path sees a draft upload (Z4, real Postgres).

A draft of the wizard has no `application_id`. The tests prove that each
application path ignores it, even for an admin and even when the draft is scanned
clean:

- the attachment item routes (URL, download, delete) answer 404,
- the attachment list of an application leaves it out,
- the guard `attachmentPresent` does not count it,
- the audit labels do not resolve its file name,
- the anonymization and the GDPR delete of an application keep it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep, get_current_principal
from app.modules.applications.models import Application
from app.modules.applications.service import ApplicationsService
from app.modules.audit.service import AuditService
from app.modules.auth.principal import Principal
from app.modules.files.drafts import hash_draft_token
from app.modules.files.models import Attachment
from app.modules.files.router import get_files_service
from app.modules.files.service import FilesService
from app.modules.files.storage import ObjectStorage
from app.modules.flow.context import build_base_context
from app.settings import Settings
from tests._support.guest_apps import (
    build_api,
    create_guest_application,
    guest_settings,
    seed_guest_flow,
)

pytestmark = pytest.mark.integration

_ADMIN = Principal(sub="admin-sub", roles=["admin"], email="admin@example.org")


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def get_stream(
        self, key: str, *, chunk_size: int = 64 * 1024
    ) -> AsyncIterator[bytes]:
        async def _iter() -> AsyncIterator[bytes]:
            yield self.blobs[key]

        return _iter()

    async def remove(self, key: str) -> None:
        self.blobs.pop(key, None)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


async def _clean_draft(
    maker: async_sessionmaker[AsyncSession], settings: Settings, storage: _MemoryStorage
) -> uuid.UUID:
    """Insert a draft that the scan already found clean, with its object."""
    draft_id = uuid.uuid4()
    key = f"drafts/{draft_id}/geheim.pdf"
    await storage.put(key, b"%PDF-1.4\n", "application/pdf")
    async with maker() as session:
        session.add(
            Attachment(
                id=draft_id,
                application_id=None,
                filename="geheim.pdf",
                mime="application/pdf",
                size=9,
                storage_key=key,
                scanned=True,
                scan_result="clean",
                draft_token_hash=hash_draft_token("tok", settings.magic_link_secret),
                draft_expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.commit()
    return draft_id


async def _app(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    seed = await seed_guest_flow(maker)
    return await create_guest_application(maker, seed)


async def test_item_routes_answer_404_for_a_draft_even_for_an_admin(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _MemoryStorage()
    draft_id = await _clean_draft(maker, settings, storage)
    api = build_api(migrated[1], settings, monkeypatch)

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        object_storage: ObjectStorage = storage  # pyright: ignore[reportAssignmentType]
        return FilesService(session, storage=object_storage, settings=request_settings)

    api.dependency_overrides[get_files_service] = _files
    api.dependency_overrides[get_current_principal] = lambda: _ADMIN
    with TestClient(api) as client:
        for resp in (
            client.get(f"/api/attachments/{draft_id}"),
            client.get(f"/api/attachments/{draft_id}/download"),
            client.delete(f"/api/attachments/{draft_id}"),
        ):
            assert resp.status_code == 404, resp.text
            assert resp.headers["content-type"].startswith("application/problem+json")
    async with maker() as session:
        assert await session.get(Attachment, draft_id) is not None
    assert len(storage.blobs) == 1


async def test_service_paths_ignore_a_draft(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    storage = _MemoryStorage()
    app_id = await _app(maker)
    draft_id = await _clean_draft(maker, settings, storage)
    async with maker() as session:
        files = FilesService(session, storage=storage, settings=settings)  # pyright: ignore[reportArgumentType]
        assert await files.list_for_application(app_id) == []
        app = await session.get(Application, app_id)
        assert app is not None
        context = await build_base_context(session, app, manual=True)
        assert context.has_attachment is False

        audit = AuditService(session)
        labels = await audit.resolve_target_labels([("attachment", str(draft_id))])
        assert labels == {}
        assert await audit.resolve_data_ids([{"attachmentId": str(draft_id)}]) == {}

        assert await files.delete_for_application(app_id, actor="test") == 0
        await ApplicationsService(session).anonymize(app_id, actor="test")
        await ApplicationsService(session).anonymize(app_id, files=files, actor="test")
    async with maker() as session:
        row = await session.get(Attachment, draft_id)
        assert row is not None
        assert row.application_id is None
    assert len(storage.blobs) == 1


async def test_a_bound_attachment_is_still_visible(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Control case: the same paths still see a bound, clean attachment."""
    storage = _MemoryStorage()
    app_id = await _app(maker)
    async with maker() as session:
        bound = Attachment(
            application_id=app_id,
            filename="beleg.pdf",
            mime="application/pdf",
            size=9,
            storage_key=f"{app_id}/x/beleg.pdf",
            scanned=True,
            scan_result="clean",
        )
        session.add(bound)
        await session.commit()
        files = FilesService(session, storage=storage, settings=settings)  # pyright: ignore[reportArgumentType]
        listed = await files.list_for_application(app_id)
        assert [a.id for a in listed] == [bound.id]
        app = await session.get(Application, app_id)
        assert app is not None
        assert (await build_base_context(session, app, manual=True)).has_attachment
        labels = await AuditService(session).resolve_target_labels(
            [("attachment", str(bound.id))]
        )
        assert labels == {("attachment", str(bound.id)): "beleg.pdf"}
