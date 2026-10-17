"""Integration: the files of an application comment (real Postgres).

A comment binds its drafts, the comment list shows them, and the download follows the
read rule of the comment: a reader of the application downloads both visibilities,
the applicant only the files of a public comment, and anybody else gets 404. A
comment file is never an application attachment. Deleting the comment removes its
files.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.router import get_comment_mail_sender
from app.modules.auth.principal import Principal
from app.modules.files.drafts import hash_draft_token
from app.modules.files.models import Attachment
from tests._support.guest_apps import guest_settings
from tests._support.memory_storage import MemoryStorage, wire_storage
from tests._support.read_models import (
    as_applicant,
    as_principal,
    build_read_api,
    create_app,
    seed_read_world,
)

pytestmark = pytest.mark.integration

_MANAGER = Principal(
    sub="comment-manager",
    display_name="Mia",
    permissions={"application.read", "application.manage"},
)


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _draft(
    maker: async_sessionmaker[AsyncSession], pepper: str, storage: MemoryStorage, name: str
) -> uuid.UUID:
    draft_id = uuid.uuid4()
    key = f"drafts/{draft_id}/{name}"
    await storage.put(key, b"data", "application/pdf")
    async with maker() as session:
        session.add(
            Attachment(
                id=draft_id,
                filename=name,
                mime="application/pdf",
                size=4,
                storage_key=key,
                scanned=True,
                scan_result="clean",
                draft_token_hash=hash_draft_token("tok", pepper),
                draft_expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.commit()
    return draft_id


async def _noop(*_args: object) -> None:
    return None


async def test_comment_files_follow_the_read_rule_of_their_comment(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pepper = guest_settings(migrated[1]).magic_link_secret
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor="applicant")
    other_app = await create_app(maker, seed, actor="applicant", title="Anderer")
    storage = MemoryStorage()
    internal = await _draft(maker, pepper, storage, "intern.pdf")
    public = await _draft(maker, pepper, storage, "oeffentlich.pdf")
    from_applicant = await _draft(maker, pepper, storage, "antwort.pdf")
    api = build_read_api(migrated[1], monkeypatch)
    api.dependency_overrides[get_comment_mail_sender] = lambda: _noop
    wire_storage(api, storage)
    url = f"/api/applications/{app_id}/comments"
    with TestClient(api) as client:
        api.state.object_storage = storage
        as_principal(api, _MANAGER)
        posted = []
        for draft, visibility in ((internal, "internal"), (public, "public")):
            resp = client.post(
                url,
                json={
                    "body": "",
                    "visibility": visibility,
                    "attachmentIds": [str(draft)],
                    "draftToken": "tok",
                },
            )
            assert resp.status_code == 201, resp.text
            posted.append(resp.json())
        assert posted[0]["attachments"][0]["filename"] == "intern.pdf"
        listed = client.get(url).json()
        assert [[a["id"] for a in c["attachments"]] for c in listed] == [
            [str(internal)],
            [str(public)],
        ]
        for draft in (internal, public):
            assert client.get(f"/api/attachments/{draft}/download").status_code == 200
        # A comment file is no application attachment.
        files = client.get(f"/api/applications/{app_id}/attachments")
        assert files.status_code == 200, files.text
        assert {a["id"] for a in files.json()}.isdisjoint({str(internal), str(public)})

        # The applicant reads the public file only.
        as_applicant(api, app_id)
        down = client.get(f"/api/attachments/{public}/download")
        assert down.status_code == 200 and down.content == b"data"
        assert client.get(f"/api/attachments/{public}").status_code == 200
        for path in (f"/api/attachments/{internal}", f"/api/attachments/{internal}/download"):
            assert client.get(path).status_code == 404
        listed = client.get(url).json()
        assert [[a["filename"] for a in c["attachments"]] for c in listed] == [["oeffentlich.pdf"]]
        own = client.post(
            url,
            json={
                "body": "",
                "visibility": "public",
                "attachmentIds": [str(from_applicant)],
                "draftToken": "tok",
            },
        )
        assert own.status_code == 201, own.text
        assert client.post(url, json={"body": "", "visibility": "public"}).status_code == 422

        # The applicant of another application does not see the file.
        as_applicant(api, other_app)
        assert client.get(f"/api/attachments/{public}/download").status_code == 404
        # A principal without a read right on the application neither.
        as_principal(api, Principal(sub="nobody"))
        assert client.get(f"/api/attachments/{public}/download").status_code == 404

        # Deleting the comment removes its file and the object.
        as_principal(api, _MANAGER)
        deleted = client.delete(f"{url}/{posted[1]['id']}")
        assert deleted.status_code == 204, deleted.text
        assert client.get(f"/api/attachments/{public}").status_code == 404
    assert f"drafts/{public}/oeffentlich.pdf" not in storage.blobs
    async with maker() as session:
        assert await session.get(Attachment, public) is None
        row = await session.get(Attachment, from_applicant)
        assert row is not None and row.comment_id is not None and row.application_id is None


async def test_a_comment_with_files_and_the_anonymization_take_the_same_lock(
    migrated: tuple[str, str], maker: async_sessionmaker[AsyncSession]
) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.modules.applications.service import ApplicationsService
    from app.modules.files.service import FilesService
    from app.shared.errors import ValidationProblem

    pepper = guest_settings(migrated[1]).magic_link_secret
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor="applicant")
    storage = MemoryStorage()
    draft = await _draft(maker, pepper, storage, "spaet.pdf")

    async def _comment(session: AsyncSession) -> None:
        await ApplicationsService(session).add_comment(
            app_id,
            author=_MANAGER.sub,
            author_kind="principal",
            body="",
            visibility="internal",
            attachment_ids=[draft],
            draft_token="tok",
            pepper=pepper,
        )

    async with maker() as anonymizing, maker() as commenting:
        await ApplicationsService(anonymizing).anonymize(
            app_id, files=FilesService(anonymizing, storage=storage), commit=False
        )
        # The open anonymization holds the row, so the comment with files waits for
        # it instead of binding files that the anonymization does not see.
        await commenting.execute(text("SET lock_timeout = '200ms'"))
        with pytest.raises(DBAPIError, match="lock timeout"):
            await _comment(commenting)
        await commenting.rollback()
        await anonymizing.commit()

    # After the wait the comment sees the anonymization and refuses its files.
    async with maker() as session:
        with pytest.raises(ValidationProblem) as exc:
            await _comment(session)
    assert exc.value.code == "application_anonymized"
    async with maker() as session:
        row = await session.get(Attachment, draft)
    assert row is not None and row.comment_id is None
