"""Integration (echte Postgres, testcontainers): FormsService CRUD + Pin + effective.

Beweist gegen ein echtes Schema: Versionsanlage/-zählung, Aktiv-Eindeutigkeit
(partial-unique), Pin (laufende Anträge behalten ihre ``form_version_id``) und die
effektive Form inkl. Topf-Extra-Felder.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.budget.models import BudgetField, BudgetPot
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
    """Async-Session gegen die migrierte DB; ``engine`` säubert Kern-Tabellen je Test."""
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


# --------------------------------------------------------------------------- #
async def test_create_first_version_activates_type(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)

    out = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )
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
    v1 = await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))
    v2 = await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))
    assert (v1.version, v2.version) == (1, 2)


async def test_activating_new_version_deactivates_old(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    v1 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )
    v2 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )

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
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )
    await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=False)
    )
    refreshed = await session.get(ApplicationType, app_type.id)
    assert refreshed is not None and refreshed.active_form_version_id == v1.id


async def test_running_application_keeps_pinned_version(session: AsyncSession) -> None:
    """Pin: eine neue Version lässt die ``form_version_id`` laufender Anträge unberührt."""
    app_type = await _make_type(session)
    svc = FormsService(session)
    v1 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )

    flow = FlowVersion(application_type_id=app_type.id, version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    application = Application(
        type_id=app_type.id, form_version_id=v1.id, flow_version_id=flow.id, data={}
    )
    session.add(application)
    await session.commit()

    # Neue aktive Version anlegen → Pin darf den Antrag nicht umhängen.
    v2 = await svc.create_form_version(
        app_type.id, FormVersionCreate(fields=_fields(), activate=True)
    )
    pinned = await session.get(Application, application.id)
    assert pinned is not None
    assert pinned.form_version_id == v1.id != v2.id


async def test_create_version_unknown_type_404(session: AsyncSession) -> None:
    svc = FormsService(session)
    with pytest.raises(NotFoundError):
        await svc.create_form_version(
            uuid.uuid4(), FormVersionCreate(fields=_fields())
        )


# --------------------------------------------------------------------------- #
# effective_form
# --------------------------------------------------------------------------- #
async def test_effective_form_main_only(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))

    eff = await svc.get_effective_form(app_type.id)
    assert [s.key for s in eff.sections] == ["main"]
    assert {f.key for f in eff.sections[0].fields} == {"title", "amount"}
    # camelCase-Roundtrip eines promoted-Felds erhalten
    amount = next(f for f in eff.sections[0].fields if f.key == "amount")
    assert amount.is_promoted is True and amount.promote_target == "amount"


async def _add_pot(session: AsyncSession, gremium_id: uuid.UUID) -> BudgetPot:
    pot = BudgetPot(gremium_id=gremium_id, name="Topf")
    session.add(pot)
    await session.flush()
    session.add(
        BudgetField(
            budget_pot_id=pot.id,
            field={"key": "cost_center", "type": "text", "label": {"de": "Kostenstelle"}},
            order=0,
        )
    )
    await session.commit()
    return pot


async def test_effective_form_with_budget_pot(session: AsyncSession) -> None:
    app_type = await _make_type(session, has_budget=True)
    svc = FormsService(session)
    await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))

    assert app_type.gremium_id is not None
    pot = await _add_pot(session, app_type.gremium_id)

    eff = await svc.get_effective_form(app_type.id, pot.id)
    assert [s.key for s in eff.sections] == ["main", "budget"]
    assert eff.sections[1].fields[0].key == "cost_center"
    assert eff.budget_pot_id == pot.id


async def test_effective_form_pot_without_has_budget_404(session: AsyncSession) -> None:
    # N1: Typ ohne has_budget darf keinen Topf an die Form hängen.
    app_type = await _make_type(session, has_budget=False)
    svc = FormsService(session)
    await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))
    assert app_type.gremium_id is not None
    pot = await _add_pot(session, app_type.gremium_id)
    with pytest.raises(NotFoundError, match="does not support budget pots"):
        await svc.get_effective_form(app_type.id, pot.id)


async def test_effective_form_cross_gremium_pot_404(session: AsyncSession) -> None:
    # N1: ein Topf aus einem fremden Gremium darf nicht durchsickern.
    app_type = await _make_type(session, has_budget=True)
    other = await _make_type(session, has_budget=True)
    svc = FormsService(session)
    await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))
    assert other.gremium_id is not None
    foreign_pot = await _add_pot(session, other.gremium_id)
    with pytest.raises(NotFoundError, match="not available for this application type"):
        await svc.get_effective_form(app_type.id, foreign_pot.id)


async def test_effective_form_no_active_version_404(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    with pytest.raises(NotFoundError, match="no active form version"):
        await svc.get_effective_form(app_type.id)


async def test_effective_form_unknown_pot_404(session: AsyncSession) -> None:
    app_type = await _make_type(session)
    svc = FormsService(session)
    await svc.create_form_version(app_type.id, FormVersionCreate(fields=_fields()))
    with pytest.raises(NotFoundError, match="budget pot"):
        await svc.get_effective_form(app_type.id, uuid.uuid4())
