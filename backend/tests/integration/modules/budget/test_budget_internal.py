"""Integration (real Postgres): the switch "Intern" of a cost center.

- 003011: the switch is off at start, turns on at each level, is inherited by every node
  below and changes while the plan of the Haushalt is in force.
- 003012: the form field `budget_select` offers no Intern cost center, a create with one
  gives 422 `cost_centre_internal`, and an older Intern answer does not block an edit.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.service.forms import FormVersionWriter
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.budget.form_options import budget_field_options
from app.modules.budget.plan_models import BudgetPlan, BudgetPlanVersion
from app.modules.budget.plan_schemas import PlanLineSet, PlanStateSet
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_schemas import (
    BudgetNodeCreate,
    BudgetNodeOut,
    BudgetNodeUpdate,
    BudgetTreeNodeOut,
    FiscalYearCreate,
)
from app.modules.forms.schemas import FormVersionCreate
from app.settings import Settings
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ValidationProblem
from tests._support.guest_apps import GuestSeed, guest_settings, seed_guest_flow

pytestmark = pytest.mark.integration


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


async def _tree(session: AsyncSession) -> dict[str, BudgetNodeOut]:
    """Seed a Haushalt with a Titel, two Kostenstellen below it and a second Titel."""
    svc = BudgetTreeService(session, actor="tester")
    top = await svc.create_node(BudgetNodeCreate(key=f"I{uuid.uuid4().hex[:8]}", name="VS"))
    titel = await svc.create_node(BudgetNodeCreate(key="8", name="Intern", parentId=top.id))
    leaf_a = await svc.create_node(BudgetNodeCreate(key="1", name="Klausur", parentId=titel.id))
    leaf_b = await svc.create_node(BudgetNodeCreate(key="2", name="Büro", parentId=titel.id))
    other = await svc.create_node(BudgetNodeCreate(key="9", name="Offen", parentId=top.id))
    await session.commit()
    return {"top": top, "titel": titel, "a": leaf_a, "b": leaf_b, "other": other}


def _find(forest: list[BudgetTreeNodeOut], node_id: uuid.UUID) -> BudgetTreeNodeOut:
    for node in forest:
        if node.id == node_id:
            return node
        try:
            return _find(list(node.children), node_id)
        except LookupError:
            continue
    raise LookupError(node_id)


async def _set(session: AsyncSession, node_id: uuid.UUID, on: bool) -> BudgetNodeOut:
    out = await BudgetTreeService(session, actor="tester").update_node(
        node_id, BudgetNodeUpdate(internal=on)
    )
    await session.commit()
    return out


async def test_internal_is_off_at_start_and_switches_on_every_level(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        t = await _tree(session)
        assert not any(node.internal for node in t.values())
        for level in ("top", "titel", "a"):
            assert (await _set(session, t[level].id, True)).internal
            assert not (await _set(session, t[level].id, False)).internal
        entry = await session.scalar(
            select(AuditEntry)
            .where(
                AuditEntry.action == AuditAction.BUDGET_NODE_UPDATE,
                AuditEntry.target_id == str(t["a"].id),
            )
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
        assert entry is not None
        assert entry.data["before"] == {"internal": True}
        assert entry.data["after"] == {"internal": False}
        with pytest.raises(ValueError, match="internal must not be null"):
            BudgetNodeUpdate.model_validate({"internal": None})


async def test_internal_is_inherited_by_every_node_below(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        t = await _tree(session)
        await _set(session, t["b"].id, True)
        await _set(session, t["titel"].id, True)
        forest = await BudgetTreeService(session, actor="tester").get_tree()
        titel = _find(forest, t["titel"].id)
        assert (titel.internal, titel.internal_inherited) == (True, False)
        leaf_a, leaf_b = _find(forest, t["a"].id), _find(forest, t["b"].id)
        assert (leaf_a.internal, leaf_a.internal_inherited) == (False, True)
        assert (leaf_b.internal, leaf_b.internal_inherited) == (True, True)
        other = _find(forest, t["other"].id)
        assert (other.internal, other.internal_inherited) == (False, False)

        await _set(session, t["titel"].id, False)
        forest = await BudgetTreeService(session, actor="tester").get_tree()
        assert not _find(forest, t["a"].id).internal_inherited
        assert _find(forest, t["b"].id).internal


async def test_internal_switches_while_a_plan_is_in_force(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        t = await _tree(session)
        svc = BudgetTreeService(session, actor="tester")
        fy = await svc.create_fiscal_year(t["top"].id, FiscalYearCreate(year=2026))
        await svc.set_plan_switch(t["top"].id, True)
        await session.commit()
        vid = await session.scalar(
            select(BudgetPlanVersion.id)
            .join(BudgetPlan, BudgetPlan.id == BudgetPlanVersion.plan_id)
            .where(BudgetPlan.fiscal_year_id == fy.id)
        )
        assert vid is not None
        await svc.set_line(vid, t["titel"].id, PlanLineSet(side="expense"))
        await svc.set_line(vid, t["other"].id, PlanLineSet(side="income", amount=Decimal(10)))
        await svc.set_line(vid, t["a"].id, PlanLineSet(amount=Decimal(4)))
        await svc.set_line(vid, t["b"].id, PlanLineSet(amount=Decimal(6)))
        await session.commit()
        plan = await svc.set_plan_state(vid, PlanStateSet(state="in_force"))
        await session.commit()
        assert plan.versions[-1].state == "in_force"

        assert (await _set(session, t["titel"].id, True)).internal
        assert (await _set(session, t["a"].id, True)).internal


async def _form(maker: async_sessionmaker[AsyncSession], seed: GuestSeed) -> None:
    async with maker() as session:
        await FormVersionWriter(session).create_form_version(
            seed.type_id,
            FormVersionCreate(
                fields=[
                    FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True),
                    FormFieldDef(key="ks", type="budget_select", label={"de": "Kostenstelle"}),
                ],
                activate=True,
            ),
            "tester",
        )


def _payload(seed: GuestSeed, data: dict[str, Any]) -> ApplicationCreate:
    return ApplicationCreate.model_validate(
        {
            "typeId": str(seed.type_id),
            "data": {"title": "Antrag", **data},
            "applicantEmail": "gast@example.org",
            "lang": "de",
        }
    )


async def _create(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    data: dict[str, Any],
    seed: GuestSeed,
) -> uuid.UUID:
    async with maker() as session:
        app, _ = await ApplicationsService(session).create(
            _payload(seed, data), draft_pepper=settings.magic_link_secret
        )
        return app.id


async def test_the_form_field_does_not_offer_an_internal_cost_centre(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as session:
        t = await _tree(session)
        await _set(session, t["titel"].id, True)
        values = {o.value for o in await budget_field_options(session)}
    assert str(t["top"].id) in values
    assert str(t["other"].id) in values
    assert not values & {str(t["titel"].id), str(t["a"].id), str(t["b"].id)}


async def test_an_antrag_with_an_internal_cost_centre_is_refused(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    await _form(maker, seed)
    async with maker() as session:
        t = await _tree(session)
        await _set(session, t["titel"].id, True)
    for internal in (t["titel"].id, t["a"].id):
        with pytest.raises(ValidationProblem) as exc:
            await _create(maker, settings, {"ks": str(internal)}, seed)
        assert exc.value.code == "cost_centre_internal"
    assert await _create(maker, settings, {"ks": str(t["other"].id)}, seed)


async def test_an_old_answer_with_an_internal_cost_centre_does_not_block_an_edit(
    maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    seed = await seed_guest_flow(maker)
    await _form(maker, seed)
    async with maker() as session:
        t = await _tree(session)
    app_id = await _create(maker, settings, {"ks": str(t["a"].id)}, seed)
    async with maker() as session:
        await _set(session, t["titel"].id, True)
    async with maker() as session:
        out = await ApplicationsService(session).patch(
            app_id, {"title": "Neu", "ks": str(t["a"].id)}, changed_by="tester"
        )
    assert out.data["ks"] == str(t["a"].id)
    async with maker() as session:
        with pytest.raises(ValidationProblem) as exc:
            await ApplicationsService(session).patch(
                app_id, {"title": "Neu", "ks": str(t["b"].id)}, changed_by="tester"
            )
    assert exc.value.code == "cost_centre_internal"
