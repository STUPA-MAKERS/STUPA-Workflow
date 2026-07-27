"""Integration (real Postgres): anonymization scrubs the comments of the applicant.

DSGVO Art. 17 (AUD-007): `ApplicationsService.anonymize` must also delete the free
text of comments that the applicant wrote (`author_kind='applicant'`). That text can
hold personal data. Comments of a principal stay untouched.
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
from app.shared.config_schemas import FormFieldDef

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _seed_type(session: AsyncSession) -> ApplicationType:
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

    forms = FormsService(session)
    await forms.create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[
                FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
            ],
            activate=True,
        ),
        "tester",
    )

    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    session.add(
        State(
            flow_version_id=flow.id,
            key="draft",
            label_i18n={"de": "Entwurf"},
            edit_allowed=True,
            is_initial=True,
        )
    )
    await session.commit()
    return app_type


def _create_payload(app_type_id: uuid.UUID) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {
            "typeId": str(app_type_id),
            "data": {"title": "Mein Antrag"},
            "applicantEmail": "Antrag@Example.ORG",
            "applicantName": "Erika",
            "lang": "de",
        }
    )


async def test_anonymize_scrubs_applicant_comment_bodies(session: AsyncSession) -> None:
    app_type = await _seed_type(session)
    svc = ApplicationsService(session)
    app, _ = await svc.create(_create_payload(app_type.id))

    # The applicant puts PII into the free text of the comment.
    await svc.add_comment(
        app.id,
        author=None,
        author_kind="applicant",
        body="Erreichbar unter erika@example.org / 0151-1234567",
        visibility="public",
    )
    # The comment of a principal may stay.
    await svc.add_comment(
        app.id,
        author="admin",
        author_kind="principal",
        body="Bearbeitungsnotiz",
        visibility="internal",
    )

    await svc.anonymize(app.id)

    comments = await svc.list_comments(app.id, include_internal=True)
    bodies = {c.body for c in comments}
    # No free text of the applicant is left.
    assert "Erreichbar unter erika@example.org / 0151-1234567" not in bodies
    assert "[anonymisiert]" in bodies
    # The comment of the principal stays untouched.
    assert "Bearbeitungsnotiz" in bodies
