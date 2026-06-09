"""Integration (echte Postgres, testcontainers): Budget-Baum end-to-end (CR #76/#78).

Beweist gegen ein echtes Schema (data-model §1/§5.8) die drei kritischen Constraints
(testing.md, vom PO benannt):

* **Pfad-Komposition** + UNIQUE(parent,key) — Top → Kind → ``VS-800``.
* **HHJ-Disjunktheit** (R7.1f/g): überlappendes HHJ → 422.
* **Top-Down-Allokation** (R7.1b): Σ Kinder ≤ Parent → sonst 422.
* **Roll-up-Korrektheit** (R7.1c): Verbrauch eines genehmigten Antrags summiert von
  der Kostenstelle bis zur Wurzel über das ``path_key``-Präfix.
* Löschen mit Kindern → 409.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_schemas import (
    AllocationSet,
    BudgetNodeCreate,
    FiscalYearCreate,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.models import FormVersion
from app.shared.errors import ConflictError, ValidationProblem

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


async def _gremium(session: AsyncSession) -> Gremium:
    g = Gremium(name="FS Informatik", slug=f"fs-{uuid.uuid4().hex[:8]}")
    session.add(g)
    await session.commit()
    return g


def _suffix() -> str:
    """Eindeutiges, alphanumerisches Key-Suffix (Tabellen werden nicht je Test geleert)."""
    return uuid.uuid4().hex[:6]


async def test_path_composition_and_tree(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top_key = f"VS{_suffix()}"
    top = await svc.create_node(BudgetNodeCreate(key=top_key, name="VS-Mittel", gremiumId=g.id))
    child = await svc.create_node(
        BudgetNodeCreate(key="800", name="Dezentral", parentId=top.id)
    )
    assert top.path_key == top_key
    assert child.path_key == f"{top_key}-800"
    assert child.gremium_id == g.id  # Kind erbt Gremium

    tree = await svc.get_tree(gremium_id=g.id)
    roots = [n for n in tree if n.id == top.id]
    assert roots and roots[0].children[0].id == child.id


async def test_fiscal_year_disjoint(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(key=f"HJ{_suffix()}", name="Top", gremiumId=g.id)
    )
    await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(label="HHJ 2026", startDate=date(2026, 1, 1), endDate=date(2026, 12, 31)),
    )
    # Lücke erlaubt:
    await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(label="HHJ 2027", startDate=date(2027, 1, 1), endDate=date(2027, 12, 31)),
    )
    # Überlappung verboten → 422:
    with pytest.raises(ValidationProblem):
        await svc.create_fiscal_year(
            top.id,
            FiscalYearCreate(
                label="HHJ X", startDate=date(2026, 6, 1), endDate=date(2027, 6, 1)
            ),
        )


async def test_top_down_allocation_constraint(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(key=f"AL{_suffix()}", name="Top", gremiumId=g.id)
    )
    c1 = await svc.create_node(BudgetNodeCreate(key="01", name="K1", parentId=top.id))
    c2 = await svc.create_node(BudgetNodeCreate(key="02", name="K2", parentId=top.id))
    fy = await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(label="HHJ", startDate=date(2026, 1, 1), endDate=date(2026, 12, 31)),
    )
    await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("1000")))
    await svc.set_allocation(c1.id, fy.id, AllocationSet(allocated=Decimal("600")))
    # 600 + 500 = 1100 > 1000 → 422
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(c2.id, fy.id, AllocationSet(allocated=Decimal("500")))
    # 600 + 400 = 1000 ≤ 1000 → ok
    await svc.set_allocation(c2.id, fy.id, AllocationSet(allocated=Decimal("400")))
    # Parent unter verteilte Kinder-Summe senken → 422
    with pytest.raises(ValidationProblem):
        await svc.set_allocation(top.id, fy.id, AllocationSet(allocated=Decimal("900")))


async def test_committed_rollup(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(key=f"RU{_suffix()}", name="Top", gremiumId=g.id)
    )
    mid = await svc.create_node(BudgetNodeCreate(key="800", name="Mid", parentId=top.id))
    leaf = await svc.create_node(BudgetNodeCreate(key="04", name="Leaf", parentId=mid.id))
    fy = await svc.create_fiscal_year(
        top.id,
        FiscalYearCreate(label="HHJ", startDate=date(2026, 1, 1), endDate=date(2026, 12, 31)),
    )

    # Genehmigter Antrag = aktueller Flow-State in den accepted_state_keys des Top-Budgets.
    app_type = ApplicationType(key=f"t-{_suffix()}", name_i18n={})
    session.add(app_type)
    await session.flush()
    fv = FormVersion(application_type_id=app_type.id, version=1)
    flv = FlowVersion(application_type_id=app_type.id, version=1)
    session.add_all([fv, flv])
    await session.flush()
    state = State(
        flow_version_id=flv.id, key="approved", label_i18n={}, category="closed"
    )
    session.add(state)
    await session.flush()
    app = Application(
        type_id=app_type.id,
        form_version_id=fv.id,
        flow_version_id=flv.id,
        current_state_id=state.id,
        budget_id=leaf.id,
        fiscal_year_id=fy.id,
        amount=Decimal("250"),
    )
    session.add(app)
    # Top-Budget: 'approved' zählt als gebunden.
    top_row = await session.get(Budget, top.id)
    assert top_row is not None
    top_row.accepted_state_keys = ["approved"]
    await session.commit()

    tree = await svc.get_tree(gremium_id=g.id)
    top_node = next(n for n in tree if n.id == top.id)

    def committed(node) -> Decimal:  # noqa: ANN001
        return node.by_fiscal_year[0].committed if node.by_fiscal_year else Decimal("0")

    mid_node = top_node.children[0]
    leaf_node = mid_node.children[0]
    # Verbrauch fließt rauf: Leaf → Mid → Top, je 250.
    assert committed(leaf_node) == Decimal("250")
    assert committed(mid_node) == Decimal("250")
    assert committed(top_node) == Decimal("250")


async def test_delete_with_children_conflicts(session: AsyncSession) -> None:
    svc = BudgetTreeService(session)
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(key=f"DL{_suffix()}", name="Top", gremiumId=g.id)
    )
    await svc.create_node(BudgetNodeCreate(key="01", name="K", parentId=top.id))
    with pytest.raises(ConflictError):
        await svc.delete_node(top.id)
