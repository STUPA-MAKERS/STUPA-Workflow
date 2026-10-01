"""Integration: draft uploads of the wizard over HTTP (Z4, real Postgres).

`POST /apply/attachments` stores a file before the application exists. The first
upload issues a draft token, each later upload sends it in `X-Draft-Token` and moves
the end of all drafts of the token. One token holds a limited number of files and
bytes. `DELETE /apply/attachments/{id}` with the token removes one draft. Each upload
and each delete writes an audit entry with `draft: true` (F12).

ALTCHA is off in these settings, so the no-op verifier passes. The router unit tests
cover the ALTCHA gate.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep
from app.modules.audit.models import AuditEntry
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


class _MemoryStorage:
    """In-memory object store. The test checks the draft rules, not MinIO."""

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


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    storage: _MemoryStorage,
) -> TestClient:
    api = build_api(migrated[1], settings, monkeypatch)

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        object_storage: ObjectStorage = storage  # pyright: ignore[reportAssignmentType]
        return FilesService(
            session, storage=object_storage, queue=None, settings=request_settings
        )

    api.dependency_overrides[get_files_service] = _files
    return TestClient(api)


def _upload(
    client: TestClient, token: str | None = None, *, name: str = "angebot.pdf"
) -> dict[str, object]:
    headers = {"X-Draft-Token": token} if token is not None else {}
    resp = client.post(
        "/api/apply/attachments",
        files={"file": (name, _PDF, "application/pdf")},
        data={"field_key": "angebote", "is_comparison_offer": "true"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _drafts(maker: async_sessionmaker[AsyncSession]) -> list[Attachment]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(Attachment)
                    .where(Attachment.application_id.is_(None))
                    .order_by(Attachment.created_at)
                )
            ).all()
        )


async def _audits(maker: async_sessionmaker[AsyncSession]) -> list[AuditEntry]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(AuditEntry)
                    .where(AuditEntry.target_type == "attachment")
                    .order_by(AuditEntry.id)
                )
            ).all()
        )


async def test_first_upload_issues_a_token_and_later_uploads_extend_it(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = guest_settings(migrated[1])
    storage = _MemoryStorage()
    before = datetime.now(UTC)
    with _client(migrated, settings, monkeypatch, storage) as client:
        first = _upload(client)
        token = first["draftToken"]
        assert isinstance(token, str) and len(token) >= 32
        assert first["scanned"] is False
        assert first["is_comparison_offer"] is True
        second = _upload(client, token, name="zweites.pdf")
        assert second["draftToken"] == token

    rows = await _drafts(maker)
    assert {str(r.id) for r in rows} == {first["id"], second["id"]}
    for row in rows:
        assert row.application_id is None
        assert row.field_key == "angebote"
        assert row.is_comparison_offer is True
        assert row.storage_key is not None
        assert row.storage_key.startswith(f"drafts/{row.id}/")
        # The database keeps the HMAC of the token, never the token.
        assert row.draft_token_hash is not None
        assert row.draft_token_hash != token.encode()
        assert row.draft_expires_at is not None
        assert row.draft_expires_at > before + timedelta(days=6, hours=23)
    # Both drafts share one end: the second upload moved the first one too.
    assert rows[0].draft_expires_at == rows[1].draft_expires_at
    assert len(storage.blobs) == 2

    audits = await _audits(maker)
    assert [a.action for a in audits] == ["attachment_upload", "attachment_upload"]
    assert audits[0].actor == "applicant"
    assert audits[0].data == {
        "draft": True,
        "fieldKey": "angebote",
        "isComparisonOffer": True,
        "mime": "application/pdf",
        "size": len(_PDF),
    }


async def test_unknown_or_expired_token_is_rejected(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = guest_settings(migrated[1])
    with _client(migrated, settings, monkeypatch, _MemoryStorage()) as client:
        resp = client.post(
            "/api/apply/attachments",
            files={"file": ("a.pdf", _PDF, "application/pdf")},
            headers={"X-Draft-Token": "invented-token"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert resp.json()["code"] == "draft_token_invalid"

        token = _upload(client)["draftToken"]
        async with maker() as session:
            for row in (await session.scalars(select(Attachment))).all():
                row.draft_expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()
        resp = client.post(
            "/api/apply/attachments",
            files={"file": ("b.pdf", _PDF, "application/pdf")},
            headers={"X-Draft-Token": str(token)},
        )
        assert resp.status_code == 422, resp.text
    assert len(await _drafts(maker)) == 1


async def test_file_and_byte_limits_per_token(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = guest_settings(migrated[1]).model_copy(
        update={"attachment_draft_max_files": 2}
    )
    with _client(migrated, settings, monkeypatch, _MemoryStorage()) as client:
        token = str(_upload(client)["draftToken"])
        _upload(client, token)
        resp = client.post(
            "/api/apply/attachments",
            files={"file": ("c.pdf", _PDF, "application/pdf")},
            headers={"X-Draft-Token": token},
        )
        assert resp.status_code == 413, resp.text
        assert resp.json()["code"] == "draft_quota_exceeded"
        # A new token starts a new draft with its own limit.
        _upload(client)

    settings = guest_settings(migrated[1]).model_copy(
        update={"attachment_draft_max_bytes": len(_PDF) + 1}
    )
    with _client(migrated, settings, monkeypatch, _MemoryStorage()) as client:
        token = str(_upload(client)["draftToken"])
        resp = client.post(
            "/api/apply/attachments",
            files={"file": ("d.pdf", _PDF, "application/pdf")},
            headers={"X-Draft-Token": token},
        )
        assert resp.status_code == 413, resp.text
        assert resp.json()["code"] == "draft_quota_exceeded"
    assert len(await _drafts(maker)) == 4


async def test_mime_sniff_and_size_cap_apply(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = guest_settings(migrated[1]).model_copy(
        update={"attachment_max_bytes": 64}
    )
    with _client(migrated, settings, monkeypatch, _MemoryStorage()) as client:
        resp = client.post(
            "/api/apply/attachments",
            files={"file": ("x.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        )
        assert resp.status_code == 415, resp.text
        resp = client.post(
            "/api/apply/attachments",
            files={"file": ("big.pdf", _PDF + b"x" * 100, "application/pdf")},
        )
        assert resp.status_code == 413, resp.text
    assert await _drafts(maker) == []


async def test_delete_needs_the_owning_token(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = guest_settings(migrated[1])
    storage = _MemoryStorage()
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    async with maker() as session:
        bound = Attachment(
            application_id=app_id,
            filename="bound.pdf",
            mime="application/pdf",
            size=3,
            storage_key=f"{app_id}/x/bound.pdf",
        )
        session.add(bound)
        await session.commit()
        bound_id = bound.id

    with _client(migrated, settings, monkeypatch, storage) as client:
        mine = _upload(client)
        token = str(mine["draftToken"])
        other = _upload(client)
        other_token = str(other["draftToken"])

        # Another token, an unknown id and a bound attachment all give 404.
        for target, header in (
            (mine["id"], other_token),
            (str(uuid.uuid4()), token),
            (str(bound_id), token),
        ):
            resp = client.delete(
                f"/api/apply/attachments/{target}", headers={"X-Draft-Token": header}
            )
            assert resp.status_code == 404, resp.text
            assert resp.headers["content-type"].startswith("application/problem+json")
        # Without the header the route answers 422.
        assert client.delete(f"/api/apply/attachments/{mine['id']}").status_code == 422

        resp = client.delete(
            f"/api/apply/attachments/{mine['id']}", headers={"X-Draft-Token": token}
        )
        assert resp.status_code == 204, resp.text

    remaining = await _drafts(maker)
    assert [str(r.id) for r in remaining] == [other["id"]]
    assert len(storage.blobs) == 1
    audits = await _audits(maker)
    deletes = [a for a in audits if a.action == "attachment_delete"]
    assert len(deletes) == 1
    assert deletes[0].target_id == mine["id"]
    assert deletes[0].data == {"draft": True}
    async with maker() as session:
        assert await session.get(Attachment, bound_id) is not None
