"""Integration: the attachment item routes mirror the list visibility.

The tests run against a real Postgres through testcontainers.

An unconfirmed guest submission (`email_confirmed_at IS NULL`) stays invisible in
`list_applications` and `list_tasks`. These tests prove that the `FilesService` read
paths (`list_for_application`, `signed_url`, `download_bytes`) also answer 404 for a
principal or Gremium read (`allow_unconfirmed=False`). They do not hand out the
separated PII, the attachments, of the unconfirmed submission. The owning applicant
still reads them over a magic link, where `allow_unconfirmed` defaults to True.
Confirmed applications stay readable as well.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError

pytestmark = pytest.mark.integration


class _StubStorage:
    """In-memory `ObjectStorage` stub.

    It lets `signed_url` and `download_bytes` pass the storage path without a 503. The
    visibility gate is the subject of the test.
    """

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self._blobs[key]

    async def get_stream(
        self, key: str, *, chunk_size: int = 64 * 1024
    ) -> AsyncIterator[bytes]:
        # `ObjectStorage.get_stream` is a coroutine that returns an AsyncIterator. It is
        # not an async generator. Therefore this stub returns an inner generator.
        async def _iter() -> AsyncIterator[bytes]:
            yield self._blobs[key]

        return _iter()

    async def remove(self, key: str) -> None:
        self._blobs.pop(key, None)

    def presigned_get_url(
        self, key: str, *, expires_seconds: int, download_name: str | None = None
    ) -> str:
        return f"memory://{key}"


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
    ]


async def _seed_type(session: AsyncSession) -> tuple[ApplicationType, State]:
    """Create a type with an active form version and a flow with an initial state.

    This is the canonical seed, the same one as `test_applications_service._seed_type`.
    """
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id,
        key=f"t-{uuid.uuid4()}",
        name_i18n={},
        has_budget=False,
    )
    session.add(app_type)
    await session.commit()

    await FormsService(session).create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester"
    )

    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    draft = State(
        flow_version_id=flow.id,
        key="draft",
        label_i18n={"de": "Entwurf"},
        edit_allowed=True,
        is_initial=True,
    )
    session.add(draft)
    await session.commit()
    return app_type, draft


def _payload(app_type_id: uuid.UUID) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {
            "typeId": str(app_type_id),
            "data": {"title": "Mein Antrag"},
            "applicantEmail": "antrag@example.org",
            "applicantName": "Erika",
            "lang": "de",
        }
    )


async def _add_clean_attachment(
    svc: FilesService, application_id: uuid.UUID
) -> uuid.UUID:
    """Create a clean-scanned attachment row and its storage object directly.

    This skips the upload path and the worker path. Only the visibility gate matters
    here.
    """
    storage_key = f"{application_id}/{uuid.uuid4().hex}/note.txt"
    assert svc.storage is not None
    await svc.storage.put(storage_key, b"PII-payload", "text/plain")
    att = Attachment(
        application_id=application_id,
        field_key=None,
        filename="note.txt",
        mime="text/plain",
        size=11,
        storage_key=storage_key,
        scanned=True,
        scan_result="clean",
        is_comparison_offer=False,
    )
    svc.session.add(att)
    await svc.session.commit()
    return att.id


async def test_unconfirmed_guest_attachments_hidden_from_principal_reads(
    session: AsyncSession,
) -> None:
    app_type, _ = await _seed_type(session)
    apps = ApplicationsService(session)
    # The default actor "applicant" leaves email_confirmed_at NULL. The submission stays
    # unconfirmed and invisible in the lists.
    app, _ = await apps.create(_payload(app_type.id))
    assert app.email_confirmed_at is None

    files = FilesService(session, storage=_StubStorage())
    attachment_id = await _add_clean_attachment(files, app.id)

    # For a principal or Gremium read the router passes `allow_unconfirmed=False`. The
    # attachments of the unconfirmed guest submission give 404. No PII leaks, and the
    # caller gets no existence oracle.
    with pytest.raises(NotFoundError):
        await files.list_for_application(app.id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await files.signed_url(attachment_id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await files.download_bytes(attachment_id, allow_unconfirmed=False)

    # The owning applicant comes over a magic link. There `allow_unconfirmed` defaults to
    # True, so the attachments of the own unconfirmed application stay readable.
    listed = await files.list_for_application(app.id)
    assert [a.id for a in listed] == [attachment_id]
    url = await files.signed_url(attachment_id)
    assert str(attachment_id) in url.url
    data, name, mime = await files.download_bytes(attachment_id)
    assert data == b"PII-payload" and name == "note.txt" and mime == "text/plain"


async def test_confirmed_app_attachments_readable_by_principal(
    session: AsyncSession,
) -> None:
    app_type, _ = await _seed_type(session)
    apps = ApplicationsService(session)
    # An actor other than "applicant" confirms at once, so principals read it normally.
    app, _ = await apps.create(_payload(app_type.id), actor="admin")
    assert app.email_confirmed_at is not None

    files = FilesService(session, storage=_StubStorage())
    attachment_id = await _add_clean_attachment(files, app.id)

    # A principal read with `allow_unconfirmed=False` returns the attachments of a
    # confirmed application. There is no false 404.
    listed = await files.list_for_application(app.id, allow_unconfirmed=False)
    assert [a.id for a in listed] == [attachment_id]
    url = await files.signed_url(attachment_id, allow_unconfirmed=False)
    assert str(attachment_id) in url.url
    data, _, _ = await files.download_bytes(attachment_id, allow_unconfirmed=False)
    assert data == b"PII-payload"
