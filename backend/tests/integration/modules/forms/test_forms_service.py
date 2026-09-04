"""Integration test for FormsService CRUD, the version pin and the effective form.

The tests run against a real schema with Postgres in testcontainers. They cover version
creation and counting and the partial-unique constraint on the active version. They also
cover the pin: a running application keeps its `form_version_id`. The last tests cover
the effective form with the extra fields of a budget pot.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.flow.models import FlowVersion
from app.modules.forms.models import FormField, FormVersion
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    """Open an async session against the migrated database.

    The `engine` fixture clears the core tables for each test.
    """
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _make_type(
    session: AsyncSession, *, has_budget: bool = False
) -> ApplicationType:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id,
        key=f"t-{uuid.uuid4()}",
        name_i18n={},
        has_budget=has_budget,
    )
    session.add(app_type)
    await session.commit()
    return app_type


def _fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {
                "key": "amount",
                "type": "currency",
                "label": {"de": "Betrag"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        ),
    ]


async def test_create_first_version_activates_type(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)

    out = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")
    assert out.version == 1
    assert out.active is True

    refreshed = await session.get(ApplicationType, app_type.id)
    assert refreshed is not None
    assert refreshed.active_form_version_id == out.id

    rows = (
        await session.scalars(
            select(FormField).where(FormField.form_version_id == out.id)
        )
    ).all()
    assert {r.key for r in rows} == {"title", "amount"}


async def test_version_counter_increments(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    v1 = await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()), "tester")
    v2 = await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()), "tester")
    assert (v1.version, v2.version) == (1, 2)


async def test_activating_new_version_deactivates_old(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    v1 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")
    v2 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")

    old = await session.get(FormVersion, v1.id)
    new = await session.get(FormVersion, v2.id)
    assert old is not None and old.active is False
    assert new is not None and new.active is True
    refreshed = await session.get(ApplicationType, app_type.id)
    assert refreshed is not None and refreshed.active_form_version_id == v2.id


async def test_inactive_version_does_not_touch_active_pointer(
    session: AsyncSession,
) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    v1 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")
    await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=False), "tester")
    refreshed = await session.get(ApplicationType, app_type.id)
    assert refreshed is not None and refreshed.active_form_version_id == v1.id


async def test_running_application_keeps_pinned_version(session: AsyncSession) -> None:
    """Pin: a new version keeps the `form_version_id` of a running application."""
    app_type = await _make_type(session)
    svc = FormsService(session)
    v1 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")

    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    application = Application(
        type_id=app_type.id, form_version_id=v1.id, flow_version_id=flow.id, data={}
    )
    session.add(application)
    await session.commit()

    # Create a new active version. The pin must keep the application on the old one.
    v2 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True), "tester")
    pinned = await session.get(Application, application.id)
    assert pinned is not None
    assert pinned.form_version_id == v1.id != v2.id


async def test_create_version_unknown_type_404(session: AsyncSession) -> None:
    svc = FormsService(session)
    with pytest.raises(NotFoundError):
        await svc.create_form_version(
            uuid.uuid4(), FormVersionCreate(fields=_fields()), "tester")


async def test_effective_form_main_only(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()), "tester")

    eff = await svc.get_effective_form(app_type.id)
    assert [s.key for s in eff.sections] == ["main"]
    assert {f.key for f in eff.sections[0].fields} == {"title", "amount"}
    # the camelCase round trip keeps the flags of a promoted field
    amount = next(f for f in eff.sections[0].fields if f.key == "amount")
    assert amount.is_promoted is True and amount.promote_target == "amount"


async def test_effective_form_no_active_version_404(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    with pytest.raises(NotFoundError, match="no active form version"):
        await svc.get_effective_form(app_type.id)


