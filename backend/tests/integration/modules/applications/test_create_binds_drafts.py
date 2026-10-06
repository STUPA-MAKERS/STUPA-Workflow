"""Integration: the create binds the draft uploads of the wizard (Z4, real Postgres).

`POST /applications` takes `attachmentIds` and `draftToken`. The create checks that
the token owns each listed draft and that no draft is expired or infected. A pending
scan is allowed. It then binds the drafts in its own transaction: `application_id`
is set, both draft columns are cleared and the storage key stays. Every reference in
a `file` field must be one of `attachmentIds`. Each failure answers 422, names the
ids and writes nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import DbSession, SettingsDep
from app.modules.applications.models import Application
from app.modules.applications.router import get_magic_link_sender
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.models import AuditEntry
from app.modules.files.drafts import DraftAttachments
from app.modules.files.models import Attachment
from app.modules.files.router import get_files_service
from app.modules.files.service import FilesService
from app.modules.files.storage import ObjectStorage
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ValidationProblem
from tests._support.guest_apps import GuestSeed, build_api, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration

_PDF = b"%PDF-1.4\n%offer\n"


class _MemoryStorage:
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


async def _seed(maker: async_sessionmaker[AsyncSession]) -> GuestSeed:
    """Seed the guest flow and give the type a form with a `file` field."""
    seed = await seed_guest_flow(maker)
    async with maker() as session:
        await FormsService(session).create_form_version(
            seed.type_id,
            FormVersionCreate(
                fields=[
                    FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
                    FormFieldDef(key="belege", type="file", label={"de": "Belege"}),
                ],
                activate=True,
            ),
            "tester",
        )
    return seed


async def _draft(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str | None = None,
) -> tuple[uuid.UUID, str]:
    """Upload one draft through the service and return its id and the token."""
    async with maker() as session:
        files = FilesService(session, storage=_storage(), settings=settings)  # pyright: ignore[reportArgumentType]
        out = await DraftAttachments(files).upload(
            token=token, filename="angebot.pdf", data=_PDF, by="applicant"
        )
    return out.id, out.draftToken


def _storage() -> Any:  # noqa: ANN401 - a duck-typed ObjectStorage
    return _MemoryStorage()


def _payload(seed: GuestSeed, **extra: Any) -> ApplicationCreate:  # noqa: ANN401
    data: dict[str, Any] = {"title": "Mit Anhang"}
    data.update(extra.pop("data", {}))
    return ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": data,
            "applicantEmail": "gast@example.org",
            "lang": "de",
            **extra,
        }
    )


async def _create(
    maker: async_sessionmaker[AsyncSession], settings: Settings, payload: ApplicationCreate
) -> uuid.UUID:
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            payload, draft_pepper=settings.magic_link_secret
        )
        return app.id


async def _count_apps(maker: async_sessionmaker[AsyncSession]) -> int:
    async with maker() as session:
        return int(await session.scalar(select(func.count(Application.id))) or 0)


async def test_create_binds_the_listed_drafts(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker)
    first, token = await _draft(maker, settings)
    second, _ = await _draft(maker, settings, token)
    unlisted, _ = await _draft(maker, settings, token)
    async with maker() as session:
        keys = {
            row.id: row.storage_key
            for row in (await session.scalars(select(Attachment))).all()
        }

    app_id = await _create(
        maker,
        settings,
        _payload(
            seed,
            data={"belege": [str(first), str(second)]},
            attachmentIds=[str(first), str(second)],
            draftToken=token,
        ),
    )

    async with maker() as session:
        rows = {row.id: row for row in (await session.scalars(select(Attachment))).all()}
        for aid in (first, second):
            assert rows[aid].application_id == app_id
            assert rows[aid].draft_token_hash is None
            assert rows[aid].draft_expires_at is None
            # The storage key stays the same after the bind.
            assert rows[aid].storage_key == keys[aid]
        # A draft that the submit does not list stays a draft until the purge.
        assert rows[unlisted].application_id is None
        assert rows[unlisted].draft_token_hash is not None
        entry = await session.scalar(
            select(AuditEntry).where(AuditEntry.action == "application_create")
        )
        assert entry is not None
        assert entry.data["attachments"] == 2


async def test_pending_scan_is_allowed_and_stays_quarantined(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker)
    aid, token = await _draft(maker, settings)
    app_id = await _create(
        maker, settings, _payload(seed, attachmentIds=[str(aid)], draftToken=token)
    )
    async with maker() as session:
        row = await session.get(Attachment, aid)
        assert row is not None
        assert row.application_id == app_id
        assert row.scanned is False


async def test_missing_expired_foreign_and_infected_drafts_give_422(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker)
    good, token = await _draft(maker, settings)
    expired, _ = await _draft(maker, settings, token)
    infected, _ = await _draft(maker, settings, token)
    foreign, _ = await _draft(maker, settings)
    unknown = uuid.uuid4()
    async with maker() as session:
        row = await session.get(Attachment, expired)
        assert row is not None
        row.draft_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        hit = await session.get(Attachment, infected)
        assert hit is not None
        hit.scanned = True
        hit.scan_result = "Eicar-Test-Signature"
        hit.storage_key = None
        await session.commit()

    ids = [good, expired, infected, foreign, unknown]
    with pytest.raises(ValidationProblem) as caught:
        await _create(
            maker,
            settings,
            _payload(seed, attachmentIds=[str(i) for i in ids], draftToken=token),
        )
    assert caught.value.code == "draft_attachments_missing"
    assert caught.value.errors is not None
    named = {e.field for e in caught.value.errors}
    assert named == {f"attachmentIds.{i}" for i in (expired, infected, foreign, unknown)}
    assert await _count_apps(maker) == 0
    async with maker() as session:
        row = await session.get(Attachment, good)
        assert row is not None
        assert row.application_id is None


async def test_file_field_must_reference_listed_drafts(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker)
    aid, token = await _draft(maker, settings)
    stray = uuid.uuid4()
    with pytest.raises(ValidationProblem) as caught:
        await _create(
            maker,
            settings,
            _payload(
                seed,
                data={"belege": [str(aid), str(stray), "not-a-uuid"]},
                attachmentIds=[str(aid)],
                draftToken=token,
            ),
        )
    assert caught.value.errors is not None
    assert [e.field for e in caught.value.errors] == ["data.belege", "data.belege"]
    assert str(stray) in caught.value.errors[0].msg
    assert await _count_apps(maker) == 0


async def test_ids_without_token_give_422(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await _seed(maker)
    aid, _ = await _draft(maker, settings)
    with pytest.raises(ValidationProblem) as caught:
        await _create(maker, settings, _payload(seed, attachmentIds=[str(aid)]))
    assert caught.value.errors is not None
    assert caught.value.errors[0].field == "draftToken"
    assert await _count_apps(maker) == 0


async def test_without_drafts_the_create_is_unchanged(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """The upload after the create stays possible: no drafts, no draft check."""
    seed = await _seed(maker)
    app_id = await _create(maker, settings, _payload(seed, data={"belege": "freitext"}))
    async with maker() as session:
        assert await session.get(Application, app_id) is not None


async def test_http_submit_binds_drafts_and_names_missing_ids(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await _seed(maker)
    storage = _MemoryStorage()
    api = build_api(migrated[1], settings, monkeypatch)

    def _files(session: DbSession, request_settings: SettingsDep) -> FilesService:
        object_storage: ObjectStorage = storage  # pyright: ignore[reportAssignmentType]
        return FilesService(session, storage=object_storage, settings=request_settings)

    async def _sender(_settings: Settings, to: str, app_id: uuid.UUID, _pool: Any) -> None:  # noqa: ANN401
        return None

    api.dependency_overrides[get_files_service] = _files
    api.dependency_overrides[get_magic_link_sender] = lambda: _sender
    with TestClient(api) as client:
        up = client.post(
            "/api/apply/attachments",
            files={"file": ("angebot.pdf", _PDF, "application/pdf")},
            data={"field_key": "belege"},
        )
        assert up.status_code == 201, up.text
        draft = up.json()
        missing = str(uuid.uuid4())
        body = {
            "typeId": str(seed.type_id),
            "data": {"title": "HTTP", "belege": [draft["id"]]},
            "applicantEmail": "gast@example.org",
            "lang": "de",
            "attachmentIds": [draft["id"], missing],
            "draftToken": draft["draftToken"],
        }
        resp = client.post("/api/applications", json=body)
        assert resp.status_code == 422, resp.text
        problem = resp.json()
        assert problem["code"] == "draft_attachments_missing"
        assert [e["field"] for e in problem["errors"]] == [f"attachmentIds.{missing}"]

        body["attachmentIds"] = [draft["id"]]
        resp = client.post("/api/applications", json=body)
        assert resp.status_code == 201, resp.text
        app_id = resp.json()["applicationId"]

    async with maker() as session:
        row = await session.get(Attachment, uuid.UUID(draft["id"]))
        assert row is not None
        assert str(row.application_id) == app_id
        assert row.storage_key is not None
        assert row.storage_key.startswith("drafts/")
