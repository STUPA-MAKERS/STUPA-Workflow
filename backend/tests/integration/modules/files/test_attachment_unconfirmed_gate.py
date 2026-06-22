"""Integration (echte Postgres, testcontainers): #AUD-032 — die Anhang-Item-Routen
spiegeln die Listen-Sichtbarkeit.

Eine unbestätigte Gast-Einreichung (``email_confirmed_at IS NULL``) ist in
``list_applications``/``list_tasks`` unsichtbar. Diese Tests beweisen, dass die
``FilesService``-Lesepfade (``list_for_application``/``signed_url``/``download_bytes``)
für einen Principal/Gremium-Read (``allow_unconfirmed=False``) ebenso 404 liefern —
also die separierte PII (Anhänge) der unbestätigten Einreichung NICHT freigeben — und
dass die besitzende Antragstellerin (Magic-Link → Default ``allow_unconfirmed=True``)
sowie bestätigte Anträge weiterhin gelesen werden können.
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
    """In-Memory ``ObjectStorage`` — nur damit ``signed_url``/``download_bytes`` den
    Storage-Pfad (kein 503) durchlaufen; der Sichtbarkeits-Gate ist der Prüfgegenstand."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self._blobs[key]

    async def get_stream(
        self, key: str, *, chunk_size: int = 64 * 1024
    ) -> AsyncIterator[bytes]:
        yield self._blobs[key]

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
    """Typ mit aktiver Form-Version + Flow (Initial-State) — kanonischer Seed wie in
    ``test_applications_service._seed_type``."""
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
    """Direkt eine *clean-gescannte* Anhang-Zeile + Storage-Objekt anlegen (umgeht den
    Upload-/Worker-Pfad; hier zählt allein der Sichtbarkeits-Gate)."""
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
    # actor="applicant" ⇒ ``email_confirmed_at IS NULL`` (unbestätigt, listen-unsichtbar).
    app, _ = await apps.create(_payload(app_type.id))
    assert app.email_confirmed_at is None

    files = FilesService(session, storage=_StubStorage())
    attachment_id = await _add_clean_attachment(files, app.id)

    # Principal/Gremium (Router → ``allow_unconfirmed=False``): die Anhänge der
    # unbestätigten Gast-Einreichung sind 404 — kein PII-Leak, kein Existenz-Orakel.
    with pytest.raises(NotFoundError):
        await files.list_for_application(app.id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await files.signed_url(attachment_id, allow_unconfirmed=False)
    with pytest.raises(NotFoundError):
        await files.download_bytes(attachment_id, allow_unconfirmed=False)

    # Besitzende Antragstellerin (Magic-Link → Default ``allow_unconfirmed=True``):
    # voller Zugriff auf die Anhänge des eigenen, noch unbestätigten Antrags.
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
    # actor != "applicant" ⇒ sofort bestätigt → für Principals normal lesbar.
    app, _ = await apps.create(_payload(app_type.id), actor="admin")
    assert app.email_confirmed_at is not None

    files = FilesService(session, storage=_StubStorage())
    attachment_id = await _add_clean_attachment(files, app.id)

    # Principal-Read (allow_unconfirmed=False) liefert die Anhänge eines bestätigten
    # Antrags ganz normal — kein falsches 404.
    listed = await files.list_for_application(app.id, allow_unconfirmed=False)
    assert [a.id for a in listed] == [attachment_id]
    url = await files.signed_url(attachment_id, allow_unconfirmed=False)
    assert str(attachment_id) in url.url
    data, _, _ = await files.download_bytes(attachment_id, allow_unconfirmed=False)
    assert data == b"PII-payload"
