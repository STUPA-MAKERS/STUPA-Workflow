"""Integration (echte Postgres, testcontainers): Budget-Modul end-to-end (T-17).

Beweist gegen ein echtes Schema (data-model §1-3, SDS-A1/A2):
Topf-CRUD + Extra-Felder, Antrag→Topf-Zuordnung (requested-Entry aus promoted amount),
Lebenszyklus reserve/book, Überbuchungsschutz (Topf-Total), Extra-Felder in der
effektiven Form **nur** bei Topf-Zuordnung, sowie Rollup-Statistik inkl.
``REFRESH MATERIALIZED VIEW [CONCURRENTLY]``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.budget.models import BudgetEntry
from app.modules.budget.schemas import AssignRequest, BudgetPotCreate, BudgetPotUpdate
from app.modules.budget.service import BudgetService
from app.modules.budget.stats import BudgetStatsService
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError

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


def _type_fields() -> list[FormFieldDef]:
    return [
        FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
        FormFieldDef.model_validate(
            {
                "key": "cost",
                "type": "currency",
                "label": {"de": "Kosten"},
                "isPromoted": True,
                "promoteTarget": "amount",
            }
        ),
    ]


async def _seed_type(session: AsyncSession) -> tuple[ApplicationType, Gremium, State]:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=True
    )
    session.add(app_type)
    await session.commit()

    await FormsService(session).create_form_version(
        app_type.id, FormVersionCreate(fields=_type_fields(), activate=True)
    )
    flow = FlowVersion(
        application_type_id=app_type.id, version=1, active=True, editor_layout={}
    )
    session.add(flow)
    await session.flush()
    draft = State(
        flow_version_id=flow.id, key="draft", label_i18n={"de": "Entwurf"},
        category="open", edit_allowed=True, is_initial=True,
    )
    session.add(draft)
    app_type.active_flow_version_id = flow.id
    await session.commit()
    return app_type, gremium, draft


async def _make_application(
    session: AsyncSession, app_type: ApplicationType, cost: str
) -> uuid.UUID:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "Antrag", "cost": cost},
                "applicantEmail": "a@example.org",
                "lang": "de",
            }
        )
    )
    return app.id


def _extra_field() -> FormFieldDef:
    return FormFieldDef(key="kostenstelle", type="text", label={"de": "Kostenstelle"})


# --------------------------------------------------------------- pot CRUD + fields
async def test_pot_crud_and_extra_fields_in_effective_form(session: AsyncSession) -> None:
    app_type, gremium, _ = await _seed_type(session)
    svc = BudgetService(session)

    pot = await svc.create_pot(
        BudgetPotCreate(
            gremiumId=gremium.id, name="Sachmittel", total=Decimal("1000.00"),
            period="2026", fields=[_extra_field()],
        )
    )
    assert pot.total == Decimal("1000.00")
    assert [f.key for f in pot.fields] == ["kostenstelle"]

    forms = FormsService(session)
    # Ohne Topf: nur Typ-Felder (keine budget-Sektion).
    plain = await forms.get_effective_form(app_type.id)
    assert {s.key for s in plain.sections} == {"main"}
    # Mit Topf: Extra-Feld erscheint in der budget-Sektion.
    with_pot = await forms.get_effective_form(app_type.id, pot.id)
    budget_section = next(s for s in with_pot.sections if s.key == "budget")
    assert [f.key for f in budget_section.fields] == ["kostenstelle"]

    # Update: Total + Felder ersetzen.
    updated = await svc.update_pot(
        pot.id, BudgetPotUpdate(total=Decimal("500.00"), fields=[])
    )
    assert updated.total == Decimal("500.00")
    assert updated.fields == []

    listed = await svc.list_pots(gremium_id=gremium.id, period="2026")
    assert len(listed) == 1


# ------------------------------------------------------- assign + lifecycle + overbook
async def test_assign_reserve_book_and_overbooking(session: AsyncSession) -> None:
    app_type, gremium, _ = await _seed_type(session)
    svc = BudgetService(session)
    pot = await svc.create_pot(
        BudgetPotCreate(gremiumId=gremium.id, name="Topf", total=Decimal("100.00"))
    )

    app1 = await _make_application(session, app_type, "60.00")
    app2 = await _make_application(session, app_type, "60.00")

    out1 = await svc.assign(app1, AssignRequest(budgetPotId=pot.id), actor="admin")
    assert out1.stage == "requested"
    assert out1.amount == Decimal("60.00")
    assert out1.budget_pot_id == pot.id

    # requested zählt nicht gegen das Total → beide reservierbar? Nein: 60+60 > 100.
    await svc.assign(app2, AssignRequest(budgetPotId=pot.id), actor="admin")
    reserved1 = await svc.reserve(app1, actor="admin")
    assert reserved1.stage == "reserved"

    with pytest.raises(ConflictError):
        await svc.reserve(app2, actor="admin")  # 60 (reserviert) + 60 > 100

    # Vorrücken app1 reserved→approved bleibt im Budget.
    booked = await svc.book(app1, actor="admin")
    assert booked.stage == "approved"

    # Detail-Auslastung (live).
    detail = await svc.get_pot(pot.id)
    assert detail.usage.approved == Decimal("60.00")
    assert detail.usage.available == Decimal("40.00")


async def test_assign_blocked_for_non_budget_type(session: AsyncSession) -> None:
    app_type, gremium, _ = await _seed_type(session)
    app_type.has_budget = False
    await session.commit()
    svc = BudgetService(session)
    pot = await svc.create_pot(BudgetPotCreate(gremiumId=gremium.id, name="T"))
    app1 = await _make_application(session, app_type, "10.00")
    from app.shared.errors import ValidationProblem

    with pytest.raises(ValidationProblem):
        await svc.assign(app1, AssignRequest(budgetPotId=pot.id), actor="admin")


async def test_unassign_removes_entry(session: AsyncSession) -> None:
    app_type, gremium, _ = await _seed_type(session)
    svc = BudgetService(session)
    pot = await svc.create_pot(BudgetPotCreate(gremiumId=gremium.id, name="T"))
    app1 = await _make_application(session, app_type, "10.00")
    await svc.assign(app1, AssignRequest(budgetPotId=pot.id), actor="admin")

    await svc.assign(app1, AssignRequest(budgetPotId=None), actor="admin")
    remaining = (
        await session.execute(
            select(BudgetEntry).where(BudgetEntry.application_id == app1)
        )
    ).scalar_one_or_none()
    assert remaining is None


async def test_set_stage_without_assignment_404(session: AsyncSession) -> None:
    app_type, _, _ = await _seed_type(session)
    app1 = await _make_application(session, app_type, "10.00")
    with pytest.raises(NotFoundError):
        await BudgetService(session).reserve(app1, actor="admin")


# ----------------------------------------------------------- stats + MV refresh
async def test_stats_after_refresh(session: AsyncSession, migrated: tuple[str, str]) -> None:
    app_type, gremium, _ = await _seed_type(session)
    svc = BudgetService(session)
    pot = await svc.create_pot(
        BudgetPotCreate(gremiumId=gremium.id, name="Topf", total=Decimal("100.00"), period="2026")
    )
    app1 = await _make_application(session, app_type, "30.00")
    await svc.assign(app1, AssignRequest(budgetPotId=pot.id), actor="admin")
    await svc.reserve(app1, actor="admin")

    stats_svc = BudgetStatsService(session)
    # Vor dem Refresh ist die MV leer.
    before = await stats_svc.usage(budget_pot_id=pot.id)
    assert before[0].reserved == Decimal("0")

    await stats_svc.refresh(concurrently=False)
    after = await stats_svc.stats(gremium_id=gremium.id, period="2026")
    pot_usage = next(p for p in after.pots if p.budget_pot_id == pot.id)
    assert pot_usage.reserved == Decimal("30.00")
    assert pot_usage.available == Decimal("70.00")
    assert any(b.count >= 1 for b in after.status_distribution)

    # CONCURRENTLY-Pfad (Worker) auf AUTOCOMMIT-Verbindung — beweist Unique-Index.
    auto_eng = create_async_engine(migrated[1], isolation_level="AUTOCOMMIT")
    auto_maker = async_sessionmaker(auto_eng, expire_on_commit=False)
    async with auto_maker() as auto_session:
        await BudgetStatsService(auto_session).refresh(concurrently=True)
    await auto_eng.dispose()
