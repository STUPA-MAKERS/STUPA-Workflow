"""Integration (echte Postgres, testcontainers): Audit-Log-Revert über Domänen hinweg
(#config-versioning).

Beweist gegen ein echtes Schema, dass :class:`RevertService` nicht nur Config-Changes,
sondern auch **Buchungen/Budget-Änderungen** und **Antrags-Zustandsübergänge**
zurücknimmt:

* Buchung (``budget_expense_create``) → gelöscht, eine dadurch bezahlte Rechnung wieder
  ``open``.
* Umbuchung (``budget_transfer_create``) → beide Zeilen gelöscht.
* Kostenstelle anlegen/ändern, Zuteilung setzen, Buchung ändern → Inverse / Vorwert.
* Statuswechsel → Antrag zurück in den Vorzustand (+ Redo); ``stale_revert`` bei
  zwischenzeitlichem Wechsel.
* Löschungen sind **nicht** revertierbar (``not_revertable``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium
from app.modules.applications.models import Application, StatusEvent
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget, BudgetExpense, Invoice
from app.modules.budget.tree_schemas import (
    AllocationSet,
    BudgetNodeCreate,
    BudgetNodeUpdate,
    ExpenseCreate,
    ExpenseUpdate,
    FiscalYearCreate,
    InvoiceCreate,
    TransferCreate,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.modules.config_revision.revert import RevertService
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.flow.service import FlowService
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError

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


async def _gremium(session: AsyncSession) -> Gremium:
    g = Gremium(name="FS", slug=f"fs-{uuid.uuid4().hex[:8]}")
    session.add(g)
    await session.commit()
    return g


async def _audit_id(session: AsyncSession, action: AuditAction, target_id: str) -> int:
    """Jüngste Audit-Eintrags-Id für (action, target_id) — der zu revertierende Vorgang."""
    return (
        await session.execute(
            select(AuditEntry.id)
            .where(AuditEntry.action == action, AuditEntry.target_id == target_id)
            .order_by(AuditEntry.id.desc())
            .limit(1)
        )
    ).scalar_one()


async def _top_with_fy(
    session: AsyncSession, svc: BudgetTreeService
) -> tuple[Budget, uuid.UUID]:
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(key=f"VS{_suffix()}", name="Top", gremiumId=g.id)
    )
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    top_row = await session.get(Budget, top.id)
    assert top_row is not None
    return top_row, fy.id


# --------------------------------------------------------------------------- #
# Buchungen (budget_expense_create)
# --------------------------------------------------------------------------- #
async def test_revert_booking_deletes_expense_and_reopens_invoice(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    inv = await svc.create_invoice(
        InvoiceCreate(number=f"R-{_suffix()}", grossAmount=Decimal("50"), status="open"),
        actor="tester",
    )
    booked = await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id,
            fiscalYearId=fy_id,
            amount=Decimal("50"),
            description="mit Rechnung",
            invoiceId=inv.id,
        ),
        actor="tester",
    )
    inv_row = await session.get(Invoice, inv.id)
    assert inv_row is not None and inv_row.status == "paid"  # Buchen → bezahlt

    audit_id = await _audit_id(
        session, AuditAction.BUDGET_EXPENSE_CREATE, str(booked.id)
    )
    await RevertService(session).revert(audit_id, "admin")

    assert await session.get(BudgetExpense, booked.id) is None  # Buchung weg
    assert inv_row.status == "open"  # Rechnung wieder offen


async def test_revert_transfer_deletes_both_rows(session: AsyncSession) -> None:
    svc = BudgetTreeService(session, actor="tester")
    g = await _gremium(session)
    top = await svc.create_node(
        BudgetNodeCreate(key=f"TR{_suffix()}", name="Top", gremiumId=g.id)
    )
    a = await svc.create_node(BudgetNodeCreate(key="01", name="A", parentId=top.id))
    b = await svc.create_node(BudgetNodeCreate(key="02", name="B", parentId=top.id))
    fy = await svc.create_fiscal_year(top.id, FiscalYearCreate(year=2026))
    transfer = await svc.create_transfer(
        TransferCreate(
            fromBudgetId=a.id,
            toBudgetId=b.id,
            fiscalYearId=fy.id,
            amount=Decimal("200"),
            description="Umbuchung",
        ),
        actor="tester",
    )
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_TRANSFER_CREATE, str(transfer.transfer_id)
    )
    await RevertService(session).revert(audit_id, "admin")

    rows = (
        await session.execute(
            select(BudgetExpense).where(
                BudgetExpense.transfer_id == transfer.transfer_id
            )
        )
    ).scalars().all()
    assert rows == []


# --------------------------------------------------------------------------- #
# Budget-Änderungen
# --------------------------------------------------------------------------- #
async def test_revert_node_create_deletes_node(session: AsyncSession) -> None:
    svc = BudgetTreeService(session, actor="tester")
    g = await _gremium(session)
    node = await svc.create_node(
        BudgetNodeCreate(key=f"NC{_suffix()}", name="Weg", gremiumId=g.id)
    )
    audit_id = await _audit_id(session, AuditAction.BUDGET_NODE_CREATE, str(node.id))
    await RevertService(session).revert(audit_id, "admin")
    assert await session.get(Budget, node.id) is None


async def test_revert_node_update_restores_prior_name(session: AsyncSession) -> None:
    svc = BudgetTreeService(session, actor="tester")
    g = await _gremium(session)
    node = await svc.create_node(
        BudgetNodeCreate(key=f"NU{_suffix()}", name="Alt", gremiumId=g.id)
    )
    await svc.update_node(node.id, BudgetNodeUpdate(name="Neu"))
    audit_id = await _audit_id(session, AuditAction.BUDGET_NODE_UPDATE, str(node.id))
    await RevertService(session).revert(audit_id, "admin")
    node_row = await session.get(Budget, node.id)
    assert node_row is not None and node_row.name == "Alt"


async def test_revert_node_update_stale_when_changed_after(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    g = await _gremium(session)
    node = await svc.create_node(
        BudgetNodeCreate(key=f"NS{_suffix()}", name="Alt", gremiumId=g.id)
    )
    await svc.update_node(node.id, BudgetNodeUpdate(name="Neu"))
    audit_id = await _audit_id(session, AuditAction.BUDGET_NODE_UPDATE, str(node.id))
    # Nach der zu revertierenden Änderung erneut umbenannt → der alte Eintrag ist stale.
    await svc.update_node(node.id, BudgetNodeUpdate(name="Neuer"))
    with pytest.raises(ConflictError) as ei:
        await RevertService(session).revert(audit_id, "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_allocation_overwrite_restores_previous(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    await svc.set_allocation(top.id, fy_id, AllocationSet(allocated=Decimal("1000")))
    await svc.set_allocation(top.id, fy_id, AllocationSet(allocated=Decimal("800")))
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_ALLOCATION_SET, str(top.id)
    )
    await RevertService(session).revert(audit_id, "admin")
    alloc = await svc._allocation(top.id, fy_id)
    assert alloc is not None and alloc.allocated == Decimal("1000")


async def test_revert_first_allocation_removes_row(session: AsyncSession) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    await svc.set_allocation(top.id, fy_id, AllocationSet(allocated=Decimal("250")))
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_ALLOCATION_SET, str(top.id)
    )
    await RevertService(session).revert(audit_id, "admin")
    assert await svc._allocation(top.id, fy_id) is None


async def test_revert_allocation_stale_when_changed_after(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    await svc.set_allocation(top.id, fy_id, AllocationSet(allocated=Decimal("1000")))
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_ALLOCATION_SET, str(top.id)
    )
    # Nach der zu revertierenden Änderung erneut gesetzt → der alte Eintrag ist stale.
    await svc.set_allocation(top.id, fy_id, AllocationSet(allocated=Decimal("900")))
    with pytest.raises(ConflictError) as ei:
        await RevertService(session).revert(audit_id, "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_expense_update_restores_prior_amount(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    booked = await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id, fiscalYearId=fy_id, amount=Decimal("50"), description="x"
        ),
        actor="tester",
    )
    await svc.update_expense(
        booked.id, ExpenseUpdate(amount=Decimal("70"), description="geändert")
    )
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_EXPENSE_UPDATE, str(booked.id)
    )
    await RevertService(session).revert(audit_id, "admin")
    row = await session.get(BudgetExpense, booked.id)
    assert row is not None
    assert row.amount == Decimal("50") and row.description == "x"


async def test_revert_expense_update_stale_when_changed_after(
    session: AsyncSession,
) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    booked = await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id, fiscalYearId=fy_id, amount=Decimal("50"), description="x"
        ),
        actor="tester",
    )
    await svc.update_expense(booked.id, ExpenseUpdate(amount=Decimal("70")))
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_EXPENSE_UPDATE, str(booked.id)
    )
    # Betrag nach der zu revertierenden Änderung erneut geändert → stale.
    await svc.update_expense(booked.id, ExpenseUpdate(amount=Decimal("90")))
    with pytest.raises(ConflictError) as ei:
        await RevertService(session).revert(audit_id, "admin")
    assert ei.value.code == "stale_revert"


async def test_revert_delete_action_is_not_revertable(session: AsyncSession) -> None:
    svc = BudgetTreeService(session, actor="tester")
    top, fy_id = await _top_with_fy(session, svc)
    booked = await svc.book_expense(
        ExpenseCreate(
            budgetId=top.id, fiscalYearId=fy_id, amount=Decimal("5"), description="x"
        ),
        actor="tester",
    )
    await svc.delete_expense(booked.id)  # erzeugt budget_expense_delete (nicht reversibel)
    audit_id = await _audit_id(
        session, AuditAction.BUDGET_EXPENSE_DELETE, str(booked.id)
    )
    with pytest.raises(ConflictError) as ei:
        await RevertService(session).revert(audit_id, "admin")
    assert ei.value.code == "not_revertable"


# --------------------------------------------------------------------------- #
# Antrags-Zustandsübergänge (status_change)
# --------------------------------------------------------------------------- #
def _manager() -> Principal:
    return Principal(
        sub="mgr-1", roles=["reviewer"], permissions={"application.manage"}
    )


async def _seed_flow(
    session: AsyncSession,
) -> tuple[ApplicationType, dict[str, State]]:
    gremium = Gremium(name="G", slug=f"g-{uuid.uuid4()}")
    session.add(gremium)
    await session.flush()
    app_type = ApplicationType(
        gremium_id=gremium.id, key=f"t-{uuid.uuid4()}", name_i18n={}, has_budget=False
    )
    session.add(app_type)
    await session.commit()
    await FormsService(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"})],
            activate=True,
        ),
        "tester",
    )
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    states = {
        "draft": State(
            flow_version_id=flow.id,
            key="draft",
            label_i18n={"de": "Entwurf"},
            edit_allowed=True,
            is_initial=True,
        ),
        "review": State(
            flow_version_id=flow.id,
            key="review",
            label_i18n={"de": "Prüfung"},
            edit_allowed=True,
        ),
    }
    session.add_all(list(states.values()))
    await session.flush()
    session.add(
        Transition(
            flow_version_id=flow.id,
            from_state_id=states["draft"].id,
            to_state_id=states["review"].id,
            label_i18n={"de": "Einreichen"},
            guard={"and": [{"hasField": "title"}, {"roleIs": "reviewer"}]},
            actions=[],
            order=0,
        )
    )
    await session.commit()
    return app_type, states


async def _fire_draft_to_review(
    session: AsyncSession, app_type: ApplicationType, states: dict[str, State]
) -> Application:
    app, _ = await ApplicationsService(session).create(
        ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "Mein Antrag"},
                "applicantEmail": "a@example.org",
            }
        )
    )
    transition = (
        await session.execute(
            select(Transition).where(Transition.from_state_id == states["draft"].id)
        )
    ).scalar_one()
    await FlowService(session).fire(app.id, transition.id, _manager(), note="ok")
    return app


async def test_revert_status_change_moves_back_and_redo(
    session: AsyncSession,
) -> None:
    app_type, states = await _seed_flow(session)
    app = await _fire_draft_to_review(session, app_type, states)
    after_fire = await session.get(Application, app.id)
    assert after_fire is not None and after_fire.current_state_id == states["review"].id

    audit_id = await _audit_id(session, AuditAction.STATUS_CHANGE, str(app.id))
    await RevertService(session).revert(audit_id, "admin")
    reverted = await session.get(Application, app.id)
    assert reverted is not None and reverted.current_state_id == states["draft"].id

    # Ein umgekehrter StatusEvent (ohne transition) wurde geschrieben.
    rev_events = (
        await session.execute(
            select(StatusEvent).where(
                StatusEvent.application_id == app.id,
                StatusEvent.from_state_id == states["review"].id,
                StatusEvent.to_state_id == states["draft"].id,
                StatusEvent.transition_id.is_(None),
            )
        )
    ).scalars().all()
    assert len(rev_events) == 1

    # Redo: den Revert-Eintrag selbst zurücknehmen → wieder im review-State.
    redo_id = await _audit_id(session, AuditAction.STATUS_CHANGE, str(app.id))
    assert redo_id != audit_id
    await RevertService(session).revert(redo_id, "admin")
    redone = await session.get(Application, app.id)
    assert redone is not None and redone.current_state_id == states["review"].id


async def test_revert_status_change_stale_when_moved_on(
    session: AsyncSession,
) -> None:
    app_type, states = await _seed_flow(session)
    app = await _fire_draft_to_review(session, app_type, states)
    audit_id = await _audit_id(session, AuditAction.STATUS_CHANGE, str(app.id))
    # Antrag zieht weiter (manuell auf einen anderen State) → der alte Wechsel ist stale.
    app_row = await session.get(Application, app.id)
    assert app_row is not None
    app_row.current_state_id = states["draft"].id
    await session.commit()
    with pytest.raises(ConflictError) as ei:
        await RevertService(session).revert(audit_id, "admin")
    assert ei.value.code == "stale_revert"
