"""Integration: the frame headers of the attachment download (real Postgres).

The preview dialog of the SPA shows a PDF in an iframe of the same origin. The tests
prove the header contract of the download route with the full middleware stack:

- ``?inline=1`` on a PDF or a raster image gives an inline response that only the
  same origin may frame (``frame-ancestors 'self'``, ``X-Frame-Options: SAMEORIGIN``,
  ``sandbox``), with the sniffed type as ``Content-Type``,
- a plain download and ``?inline=1`` on any other type keep the default API set
  (``X-Frame-Options: DENY``, ``frame-ancestors 'none'``) and a forced download,
- the quarantine gate still answers 409 with the default set,
- other API routes still send the default set.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Headers
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep, get_current_principal
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from app.modules.files.router import PREVIEW_CSP, get_files_service
from app.modules.files.service import FilesService
from app.modules.files.storage import ObjectStorage
from app.settings import Settings
from tests._support.guest_apps import (
    build_api,
    create_guest_application,
    guest_settings,
    seed_guest_flow,
)

pytestmark = pytest.mark.integration

_READER = Principal(sub="reader-sub", permissions={"application.read_all"})
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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


async def _confirmed_app(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    async with maker() as session:
        await session.execute(
            update(Application)
            .where(Application.id == app_id)
            .values(email_confirmed_at=datetime.now(UTC))
        )
        await session.commit()
    return app_id


async def _attachment(
    maker: async_sessionmaker[AsyncSession],
    storage: _MemoryStorage,
    app_id: uuid.UUID,
    *,
    filename: str,
    mime: str,
    clean: bool = True,
) -> uuid.UUID:
    att_id = uuid.uuid4()
    key = f"{app_id}/{att_id.hex}/{filename}"
    data = b"%PDF-1.4\n" if mime == "application/pdf" else b"\x00" * 9
    await storage.put(key, data, mime)
    async with maker() as session:
        session.add(
            Attachment(
                id=att_id,
                application_id=app_id,
                filename=filename,
                mime=mime,
                size=len(data),
                storage_key=key,
                scanned=clean,
                scan_result="clean" if clean else None,
            )
        )
        await session.commit()
    return att_id


def _api(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    storage: _MemoryStorage,
) -> FastAPI:
    api = build_api(migrated[1], settings, monkeypatch)

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        object_storage: ObjectStorage = storage  # pyright: ignore[reportAssignmentType]
        return FilesService(session, storage=object_storage, settings=request_settings)

    api.dependency_overrides[get_files_service] = _files
    api.dependency_overrides[get_current_principal] = lambda: _READER
    return api


def _assert_deny(headers: Headers) -> None:
    assert headers.get_list("x-frame-options") == ["DENY"]
    (csp,) = headers.get_list("content-security-policy")
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'none'" in csp


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("beleg.pdf", "application/pdf"),
        ("foto.png", "image/png"),
        ("foto.jpg", "image/jpeg"),
        ("anim.gif", "image/gif"),
        ("bild.webp", "image/webp"),
    ],
)
async def test_inline_preview_may_be_framed_by_the_same_origin_only(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    mime: str,
) -> None:
    storage = _MemoryStorage()
    app_id = await _confirmed_app(maker)
    att_id = await _attachment(maker, storage, app_id, filename=filename, mime=mime)
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        resp = client.get(f"/api/attachments/{att_id}/download?inline=1")
    assert resp.status_code == 200, resp.text
    h = resp.headers
    assert h["content-type"] == mime
    assert h["content-disposition"] == f'inline; filename="{filename}"'
    assert h.get_list("x-frame-options") == ["SAMEORIGIN"]
    assert h.get_list("content-security-policy") == [PREVIEW_CSP]
    assert "frame-ancestors 'self'" in PREVIEW_CSP
    assert "default-src 'none'" in PREVIEW_CSP
    assert PREVIEW_CSP.endswith("; sandbox")
    assert h.get_list("x-content-type-options") == ["nosniff"]


async def test_plain_download_keeps_deny(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _MemoryStorage()
    app_id = await _confirmed_app(maker)
    att_id = await _attachment(
        maker, storage, app_id, filename="beleg.pdf", mime="application/pdf"
    )
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        resp = client.get(f"/api/attachments/{att_id}/download")
        other = client.get(f"/api/applications/{app_id}/attachments")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-disposition"] == 'attachment; filename="beleg.pdf"'
    _assert_deny(resp.headers)
    # Any other API route keeps the default set too.
    assert other.status_code == 200, other.text
    _assert_deny(other.headers)


async def test_inline_flag_on_an_office_file_stays_a_framing_denied_download(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _MemoryStorage()
    app_id = await _confirmed_app(maker)
    att_id = await _attachment(maker, storage, app_id, filename="antrag.docx", mime=_DOCX)
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        resp = client.get(f"/api/attachments/{att_id}/download?inline=1")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == _DOCX
    assert resp.headers["content-disposition"] == 'attachment; filename="antrag.docx"'
    _assert_deny(resp.headers)


async def test_quarantined_file_keeps_the_gate_and_deny(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _MemoryStorage()
    app_id = await _confirmed_app(maker)
    att_id = await _attachment(
        maker, storage, app_id, filename="beleg.pdf", mime="application/pdf", clean=False
    )
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        resp = client.get(f"/api/attachments/{att_id}/download?inline=1")
    assert resp.status_code == 409, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    _assert_deny(resp.headers)
