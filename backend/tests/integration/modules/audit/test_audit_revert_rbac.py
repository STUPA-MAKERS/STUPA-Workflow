"""Integration (echte Postgres, testcontainers): der Audit-Log-Revert re-asserted die
*granulare* Permission des Original-Vorgangs, nicht nur ``audit.revert`` (#AUD-018).

Beweist gegen ein echtes Schema, dass :meth:`RevertService.revert` einen Principal ohne
die jeweilige Original-Permission mit ``403`` (``ForbiddenError``) abweist — und mit der
passenden Permission durchläuft — für Config-, Budget- und Status-Reverts. ``principal=
None`` (interne Aufrufer/Tests) bleibt ungeprüft (kein Regress der Bestands-Tests).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.budget.tree_schemas import (
    BudgetNodeCreate,
    ExpenseCreate,
    FiscalYearCreate,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.modules.config_revision.revert import RevertService
from app.modules.config_revision.service import ENTITY_FORM, ConfigRevisionService
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ForbiddenError

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


def _suffix() -> str:
    return uuid.uuid4().hex[:6]


def _principal(*perms: str) -> Principal:
    """Nicht-Admin-Principal mit GENAU diesen Permissions (kein Admin-Bypass)."""
    return Principal(sub=f"u-{_suffix()}", roles=["reviewer"], permissions=set(perms))


async def _audit_id(session: AsyncSession, action: AuditAction, target_id: str) -> int:
    return (
        await session.execute(
            select(AuditEntry.id)
            .where(AuditEntry.action == action, AuditEntry.target_id == target_id)
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
    ).scalar_one()


# --------------------------------------------------------------------------- #
# Budget: budget.book verlangt; eine Rolle ohne sie wird abgewiesen.
# --------------------------------------------------------------------------- #
async def test_budget_revert_requires_budget_book(session: AsyncSession) -> None:
    svc = BudgetTreeService(session, actor="tester")
    g = Gremium(name="FS", slug=f"fs-{_suffix()}")
    session.add(g)
    await session.commit()
    top = await svc.create_node(
        BudgetNodeCreate(key=f"VS{_suffix()}", name="Top", gremiumId=g.id)
    )
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    booked = await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id, fiscalYearId=fy.id, amount=Decimal("5"), description="x"
        ),
        actor="tester",
    )
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_EXPENSE_CREATE, str(booked.id)
    )

    # audit.revert allein genügt NICHT (#AUD-018): es fehlt budget.book.
    with pytest.raises(ForbiddenError):
        await RevertService(session).revert(
            audit_id, "u", _principal("audit.revert")
        )
    # Die Buchung steht noch (kein Money-Move ohne Permission).
    assert await session.get(Budget, top.id) is not None

    # Mit budget.book läuft derselbe Revert durch.
    await RevertService(session).revert(
        audit_id, "u", _principal("audit.revert", "budget.book")
    )


async def test_budget_node_revert_requires_budget_structure(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    g = Gremium(name="FS", slug=f"fs-{_suffix()}")
    session.add(g)
    await session.commit()
    node = await svc.create_node(
        BudgetNodeCreate(key=f"NC{_suffix()}", name="Weg", gremiumId=g.id)
    )
    audit_id = await _audit_id(session, AuditAction.BUDGET_NODE_CREATE, str(node.id))

    with pytest.raises(ForbiddenError):
        await RevertService(session).revert(
            audit_id, "u", _principal("audit.revert", "budget.book")  # falsche Perm
        )
    assert await session.get(Budget, node.id) is not None

    await RevertService(session).revert(
        audit_id, "u", _principal("audit.revert", "budget.structure")
    )
    assert await session.get(Budget, node.id) is None


# --------------------------------------------------------------------------- #
# Config (Form): form.configure verlangt.
# --------------------------------------------------------------------------- #
async def _seeded_form_change(
    session: AsyncSession,
) -> tuple[str, int]:
    """Form mit zwei Versionen → der Revert der zweiten ist der zu prüfende Vorgang."""
    g = Gremium(name="G", slug=f"g-{_suffix()}")
    session.add(g)
    await session.flush()
    at = ApplicationType(
        gremium_id=g.id, key=f"t-{_suffix()}", name_i18n={}, has_budget=False
    )
    session.add(at)
    await session.commit()
    forms = FormsService(session)
    await forms.create_form_version(
        at.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="a", type="text", label={"de": "A"})],
            activate=True,
        ),
        "tester",
    )
    await forms.create_form_version(
        at.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="b", type="text", label={"de": "B"})],
            activate=True,
        ),
        "tester",
    )
    # Jüngste config_revision der Form-Entität = der zu revertierende Change.
    revisions = ConfigRevisionService(session)
    head = await revisions.head(ENTITY_FORM, str(at.id))
    assert head is not None
    audit = (
        await session.execute(
            select(AuditEntry)
            .where(AuditEntry.action == AuditAction.CONFIG_CHANGE)
            .order_by(AuditEntry.id.desc())
        )
    ).scalars()
    # den Audit-Eintrag finden, dessen data.revisionId auf head zeigt
    for entry in audit:
        if str((entry.data or {}).get("revisionId") or "") == str(head.id):
            return str(at.id), entry.id
    raise AssertionError("no config_change audit entry linked to head revision")


async def test_config_revert_requires_form_configure(session: AsyncSession) -> None:
    _, audit_id = await _seeded_form_change(session)

    with pytest.raises(ForbiddenError):
        await RevertService(session).revert(
            audit_id, "u", _principal("audit.revert")
        )

    # Mit form.configure läuft der Config-Revert durch.
    await RevertService(session).revert(
        audit_id, "u", _principal("audit.revert", "form.configure")
    )


# --------------------------------------------------------------------------- #
# Status: application.transition verlangt.
# --------------------------------------------------------------------------- #
def _manager() -> Principal:
    return Principal(
        sub="mgr-1", roles=["reviewer"], permissions={"application.manage"}
    )


async def test_status_revert_requires_application_transition(
    session: AsyncSession,
) -> None:
    g = Gremium(name="G", slug=f"g-{_suffix()}")
    session.add(g)
    await session.flush()
    at = ApplicationType(
        gremium_id=g.id, key=f"t-{_suffix()}", name_i18n={}, has_budget=False
    )
    session.add(at)
    await session.commit()
    await FormsService(session).create_form_version(
        at.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"})],
            activate=True,
        ),
        "tester",
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
    review = State(
        flow_version_id=flow.id,
        key="review",
        label_i18n={"de": "Prüfung"},
        edit_allowed=True,
    )
    session.add_all([draft, review])
    await session.flush()
    session.add(
        Transition(
            flow_version_id=flow.id,
            from_state_id=draft.id,
            to_state_id=review.id,
            label_i18n={"de": "Einreichen"},
            guard={"and": [{"hasField": "title"}, {"roleIs": "reviewer"}]},
            actions=[],
            order=0,
        )
    )
    await session.commit()

    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(at.id),
                "data": {"title": "Mein Antrag"},
                "applicantEmail": "a@example.org",
            }
        )
    )
    transition = (
        await session.execute(
            select(Transition).where(Transition.from_state_id == draft.id)
        )
    ).scalar_one()
    await FlowService(session).fire(app.id, transition.id, _manager(), note="ok")

    audit_id = await _audit_id(session, AuditAction.STATUS_CHANGE, str(app.id))

    with pytest.raises(ForbiddenError):
        await RevertService(session).revert(
            audit_id, "u", _principal("audit.revert")
        )
    after_block = await session.get(Application, app.id)
    assert after_block is not None and after_block.current_state_id == review.id

    await RevertService(session).revert(
        audit_id, "u", _principal("audit.revert", "application.transition")
    )
    reverted = await session.get(Application, app.id)
    assert reverted is not None and reverted.current_state_id == draft.id
