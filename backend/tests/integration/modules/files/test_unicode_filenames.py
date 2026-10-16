"""Integration: an upload keeps its Unicode name, the object key stays ASCII (real Postgres).

The application upload and the draft upload of the wizard both store the display name
of the client (``sanitize_display_name``): ``Einführung €.pdf`` stays
``Einführung €.pdf``. Only the last segment of the object key is ASCII
(``sanitize_storage_name``). The download answers with an ASCII ``filename`` fallback
and the exact name as ``filename*=UTF-8''…`` (RFC 6266). Starlette encodes a header as
Latin-1, so the plain form with the euro sign would fail with 500.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep, get_current_principal
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from app.modules.files.router import get_files_service
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

_PDF = b"%PDF-1.4\n%offer\n"
_NAME = "Einführung €.pdf"
_KEY_NAME = "Einfuhrung _.pdf"
_MANAGER = Principal(
    sub="manager-sub", permissions={"application.read_all", "application.manage"}
)


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


def _api(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    storage: _MemoryStorage,
) -> FastAPI:
    api = build_api(migrated[1], settings, monkeypatch)

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        object_storage: ObjectStorage = storage  # pyright: ignore[reportAssignmentType]
        return FilesService(
            session, storage=object_storage, queue=None, settings=request_settings
        )

    api.dependency_overrides[get_files_service] = _files
    api.dependency_overrides[get_current_principal] = lambda: _MANAGER
    return api


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


async def _row(maker: async_sessionmaker[AsyncSession], att_id: str) -> Attachment:
    async with maker() as session:
        row = await session.get(Attachment, uuid.UUID(att_id))
        assert row is not None
        return row


async def _mark_clean(maker: async_sessionmaker[AsyncSession], att_id: str) -> None:
    async with maker() as session:
        await session.execute(
            update(Attachment)
            .where(Attachment.id == uuid.UUID(att_id))
            .values(scanned=True, scan_result="clean")
        )
        await session.commit()


def _disposition(value: str) -> tuple[str, str]:
    """Split the header into the plain fallback and the decoded extended name."""
    kind, plain, ext = value.split("; ")
    assert kind == "attachment"
    assert plain.startswith('filename="')
    assert ext.startswith("filename*=UTF-8''")
    return plain[len('filename="') : -1], unquote(ext[len("filename*=UTF-8''") :])


async def test_application_upload_keeps_the_display_name_and_downloads_it(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _MemoryStorage()
    app_id = await _confirmed_app(maker)
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        resp = client.post(
            f"/api/applications/{app_id}/attachments",
            files={"file": (_NAME, _PDF, "application/pdf")},
        )
        assert resp.status_code == 201, resp.text
        att_id = resp.json()["id"]
        assert resp.json()["filename"] == _NAME

        row = await _row(maker, att_id)
        assert row.filename == _NAME
        assert row.storage_key is not None
        assert row.storage_key.isascii()
        assert row.storage_key.startswith(f"{app_id}/")
        assert row.storage_key.endswith(f"/{_KEY_NAME}")
        assert list(storage.blobs) == [row.storage_key]

        listed = client.get(f"/api/applications/{app_id}/attachments")
        assert listed.status_code == 200, listed.text
        assert [a["filename"] for a in listed.json()] == [_NAME]

        await _mark_clean(maker, att_id)
        download = client.get(f"/api/attachments/{att_id}/download")
    assert download.status_code == 200, download.text
    assert download.content == _PDF
    assert download.headers["content-disposition"] == (
        "attachment; filename=\"Einfuhrung _.pdf\"; "
        "filename*=UTF-8''Einf%C3%BChrung%20%E2%82%AC.pdf"
    )


@pytest.mark.parametrize(
    ("sent", "display", "key_name"),
    [
        (_NAME, _NAME, _KEY_NAME),
        ("会议记录 🧾.pdf", "会议记录 🧾.pdf", "____ _.pdf"),
        ("../../etc/Rechnung‮fdp.pdf", "Rechnungfdp.pdf", "Rechnungfdp.pdf"),
        ("Straße\u3000Ärger.pdf", "Straße Ärger.pdf", "Stra_e Arger.pdf"),
    ],
)
async def test_draft_upload_keeps_the_display_name(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    sent: str,
    display: str,
    key_name: str,
) -> None:
    storage = _MemoryStorage()
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        resp = client.post(
            "/api/apply/attachments",
            files={"file": (sent, _PDF, "application/pdf")},
            data={"field_key": "angebote", "is_comparison_offer": "false"},
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == display
    row = await _row(maker, body["id"])
    assert row.filename == display
    assert row.storage_key == f"drafts/{body['id']}/{key_name}"
    assert key_name.isascii()


async def test_download_of_a_stored_name_from_before_keeps_working(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An old row holds ``Einf_hrung.pdf`` or even a raw name; both download safely."""
    storage = _MemoryStorage()
    app_id = await _confirmed_app(maker)
    ids: list[uuid.UUID] = []
    async with maker() as session:
        for name in ["Einf_hrung.pdf", "Zoë\r\n‮.pdf"]:
            att_id = uuid.uuid4()
            key = f"{app_id}/{att_id.hex}/x.pdf"
            await storage.put(key, _PDF, "application/pdf")
            session.add(
                Attachment(
                    id=att_id,
                    application_id=app_id,
                    filename=name,
                    mime="application/pdf",
                    size=len(_PDF),
                    storage_key=key,
                    scanned=True,
                    scan_result="clean",
                )
            )
            ids.append(att_id)
        await session.commit()
    with TestClient(_api(migrated, settings, monkeypatch, storage)) as client:
        old, raw = (client.get(f"/api/attachments/{i}/download") for i in ids)
    assert old.status_code == 200, old.text
    assert _disposition(old.headers["content-disposition"]) == (
        "Einf_hrung.pdf",
        "Einf_hrung.pdf",
    )
    assert raw.status_code == 200, raw.text
    assert _disposition(raw.headers["content-disposition"]) == ("Zoe.pdf", "Zoë.pdf")
