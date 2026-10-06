"""Integration: a guest can upload in a locked state, but cannot delete (real Postgres).

Every applicant session has the edit scope (O4). Each action checks the current state.
An upload is allowed in every state, for example a receipt after the decision (Z1).
A delete is a data change, like a PATCH. In a state with `edit_allowed = false` the
attachment DELETE route answers 409 for the applicant. In an open state it deletes.

The test signs in through a real magic-link session cookie and calls the HTTP routes.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep
from app.modules.applications.models import Application
from app.modules.auth import service as auth_service
from app.modules.files.router import get_files_service
from app.modules.files.service import FilesService
from app.modules.files.storage import ObjectStorage
from app.settings import Settings
from tests._support.guest_apps import (
    GuestSeed,
    build_api,
    create_guest_application,
    guest_settings,
    issue_magic_token,
    seed_guest_flow,
)

pytestmark = pytest.mark.integration

_PDF = b"%PDF-1.4\n%receipt\n"


class _MemoryStorage:
    """In-memory object store. The test checks the state lock, not MinIO."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

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


async def _applicant_session(
    maker: async_sessionmaker[AsyncSession], settings: Settings, app_id: uuid.UUID
) -> str:
    """Redeem a fresh magic link and return the applicant session id for the cookie."""
    token = await issue_magic_token(maker, settings, app_id)
    async with maker() as session:
        _, scope, sid = await auth_service.verify_magic_link(session, settings, token=token)
        await session.commit()
    assert scope == "edit"
    return sid


async def _set_state(
    maker: async_sessionmaker[AsyncSession], app_id: uuid.UUID, state_id: uuid.UUID
) -> None:
    async with maker() as session:
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(current_state_id=state_id)
        )
        await session.commit()


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    storage: _MemoryStorage,
    sid: str,
) -> TestClient:
    api = build_api(migrated[1], settings, monkeypatch)

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        object_storage: ObjectStorage = storage  # pyright: ignore[reportAssignmentType]
        return FilesService(
            session, storage=object_storage, queue=None, settings=request_settings
        )

    api.dependency_overrides[get_files_service] = _files
    client = TestClient(api)
    client.cookies.set(settings.applicant_cookie_name, sid)
    # The session is a cookie, so a write needs the CSRF double-submit pair.
    client.cookies.set(settings.csrf_cookie_name, "csrf-test-token")
    client.headers[settings.csrf_header_name] = "csrf-test-token"
    return client


def _upload(client: TestClient, app_id: uuid.UUID) -> str:
    resp = client.post(
        f"/api/applications/{app_id}/attachments",
        files={"file": ("beleg.pdf", _PDF, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_guest_uploads_but_cannot_delete_in_a_locked_state(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed: GuestSeed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    sid = await _applicant_session(maker, settings, app_id)
    await _set_state(maker, app_id, seed.locked_state_id)
    storage = _MemoryStorage()

    with _client(migrated, settings, monkeypatch, storage, sid) as client:
        attachment_id = _upload(client, app_id)
        resp = client.delete(f"/api/attachments/{attachment_id}")
        assert resp.status_code == 409, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        listed = client.get(f"/api/applications/{app_id}/attachments")
        assert listed.status_code == 200
        assert [a["id"] for a in listed.json()] == [attachment_id]
    assert len(storage.blobs) == 1


async def test_guest_deletes_in_an_open_state(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    sid = await _applicant_session(maker, settings, app_id)
    storage = _MemoryStorage()

    with _client(migrated, settings, monkeypatch, storage, sid) as client:
        attachment_id = _upload(client, app_id)
        resp = client.delete(f"/api/attachments/{attachment_id}")
        assert resp.status_code == 204, resp.text
        listed = client.get(f"/api/applications/{app_id}/attachments")
        assert listed.json() == []
    assert storage.blobs == {}
