"""Integration (echte Postgres, testcontainers): PdfService gegen echtes Schema.

Beweist ``load_application_doc`` (Felder/Werte/PII-Ausschluss/Verlauf/Variante je
Gremium), den Job-Lebenszyklus (``create_application_job``→``get_job``), die
Idempotenz-Wiederverwendung und das ``render_job``-UNIQUE auf ``idempotency_key``.
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
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.pdf.markdown import build_application_markdown
from app.modules.pdf.service import PdfService
from app.modules.voting.models import Vote
from app.shared.config_schemas import FormFieldDef

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


def _fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {"key": "note", "type": "text", "label": {"de": "Notiz"}, "isPII": True}
        ),
    ]


async def _seed_type(session: AsyncSession, *, cd_variant: str = "makers") -> ApplicationType:
    gremium = Gremium(name="StuPa", slug=f"stupa-{uuid.uuid4()}", cd_variant=cd_variant)
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={"de": "Förderantrag"}
    )
    session.add(app_type)
    await session.commit()

    await FormsService(session).create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")
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
    return app_type


async def _create_app(session: AsyncSession, app_type: ApplicationType) -> uuid.UUID:
    payload = ApplicationCreate.model_validate(
        {
            "typeId": str(app_type.id),
            "data": {"title": "Projekt X", "note": "geheim-pii"},
            "applicantEmail": "erika@example.org",
            "applicantName": "Erika M.",
            "lang": "de",
        }
    )
    app, _ = await ApplicationsService(session).create(payload)
    await session.commit()
    return app.id


async def test_load_application_doc_and_markdown(session: AsyncSession) -> None:
    app_type = await _seed_type(session, cd_variant="makers")
    app_id = await _create_app(session, app_type)

    doc = await PdfService(session).load_application_doc(app_id)
    assert doc.type_name == "Förderantrag"
    assert doc.gremium_slug is not None and doc.gremium_slug.startswith("stupa-")
    assert doc.applicant_name == "Erika M."
    assert doc.variant == "report-makers"  # cd_variant=makers → Report-Makers-Variante
    assert doc.data["title"] == "Projekt X"
    assert len(doc.timeline) >= 1  # Initial-Status-Event aus create()

    md = build_application_markdown(doc)
    assert "Projekt X" in md
    assert "geheim-pii" not in md  # PII-Feld bleibt draußen
    assert 'typ: antrag' in md


async def test_vote_result_in_doc(session: AsyncSession) -> None:
    app_type = await _seed_type(session)
    app_id = await _create_app(session, app_type)
    vote = Vote(
        application_id=app_id,
        eligible_group="stupa",
        config={"title": {"de": "Annahme?"}},
        status="closed",
        result="passed",
    )
    session.add(vote)
    await session.commit()

    doc = await PdfService(session).load_application_doc(app_id)
    assert doc.vote is not None
    assert doc.vote.title == "Annahme?"
    assert doc.vote.result == "passed"


async def test_job_lifecycle_and_idempotency(session: AsyncSession) -> None:
    app_type = await _seed_type(session)
    app_id = await _create_app(session, app_type)
    svc = PdfService(session)

    job = await svc.create_application_job(app_id)
    await session.commit()
    assert job.status == "pending"
    assert (await svc.get_job(job.id)).id == job.id

    # Idempotenz: gleicher Key ⇒ derselbe Job (kein Doppel-Render).
    a = await svc.create_application_job(app_id, idempotency_key="evt-1")
    await session.commit()
    b = await svc.create_application_job(app_id, idempotency_key="evt-1")
    await session.commit()
    assert a.id == b.id
