"""Budget-Baum-Service (CR #76/#78): Kostenstellen-CRUD, Haushaltsjahre, Top-Down-
Zuteilung, Antrag→Kostenstelle/HHJ-Zuordnung, Baum-Sicht mit Roll-up.

Dünne I/O-Verdrahtung; alle Entscheidungen liegen in :mod:`app.modules.budget.tree_rules`
(testing.md §1: ``budget`` = kritisches Modul, 100 % Branch). problem+json bei Fehlern.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.applications.service import _title_of
from app.modules.flow.models import State
from app.modules.budget import tree_rules
from app.modules.budget.models import BudgetEntry
from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import (
    AllocationOut,
    AllocationSet,
    AssignBudgetOut,
    AssignBudgetRequest,
    BudgetApplicationOut,
    BudgetNodeCreate,
    BudgetNodeOut,
    BudgetNodeUpdate,
    BudgetTreeNodeOut,
    ExpenseCreate,
    ExpenseOut,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
    MoveFiscalYearRequest,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

_ZERO = Decimal("0")


def _node_out(b: Budget) -> BudgetNodeOut:
    return BudgetNodeOut(
        id=b.id,
        parentId=b.parent_id,
        gremiumId=b.gremium_id,
        key=b.key,
        pathKey=b.path_key,
        name=b.name,
        currency=b.currency,
        active=b.active,
        color=b.color,
        acceptedStateKeys=list(b.accepted_state_keys or []),
        deniedStateKeys=list(b.denied_state_keys or []),
    )


def _fy_out(f: FiscalYear) -> FiscalYearOut:
    return FiscalYearOut(
        id=f.id,
        budgetId=f.budget_id,
        label=f.label,
        startDate=f.start_date,
        endDate=f.end_date,
        active=f.active,
    )


class BudgetTreeService:
    """DB-gestützte Operationen des Kostenstellen-Baums (an eine Session gebunden)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --------------------------------------------------------------- low-level
    async def _get_node(self, budget_id: UUID) -> Budget:
        node = (
            await self.session.execute(select(Budget).where(Budget.id == budget_id))
        ).scalar_one_or_none()
        if node is None:
            raise NotFoundError(f"budget {budget_id} not found")
        return node

    async def _get_fiscal_year(self, fiscal_year_id: UUID) -> FiscalYear:
        fy = (
            await self.session.execute(
                select(FiscalYear).where(FiscalYear.id == fiscal_year_id)
            )
        ).scalar_one_or_none()
        if fy is None:
            raise NotFoundError(f"fiscal year {fiscal_year_id} not found")
        return fy

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(
                select(Application).where(Application.id == application_id)
            )
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _top_level(self, node: Budget) -> Budget:
        """Top-Level-Budget eines Knotens (erstes Pfad-Segment, ``parent_id IS NULL``)."""
        top_path = node.path_key.split(_SEP, 1)[0]
        top = (
            await self.session.execute(
                select(Budget).where(
                    Budget.path_key == top_path, Budget.parent_id.is_(None)
                )
            )
        ).scalar_one_or_none()
        if top is None:
            raise NotFoundError(f"top-level budget for {node.path_key!r} not found")
        return top

    # ------------------------------------------------------------- node CRUD
    async def create_node(self, payload: BudgetNodeCreate) -> BudgetNodeOut:
        """Kostenstelle anlegen. Top-Level braucht ``gremiumId``; Kinder erben Gremium."""
        if not tree_rules.is_valid_key(payload.key):
            raise ValidationProblem(
                "Invalid budget key.",
                errors=[{"field": "key", "msg": "must be alphanumeric (no '-')"}],
            )

        if payload.parent_id is None:
            # Budgets sind NICHT fest an ein Gremium gebunden (#17-Korrektur). Ein
            # optionales ``gremiumId`` wird nur — falls gesetzt — validiert; sonst NULL.
            # Wer wann mitstimmt, regelt der Flow (z. B. Betragsschwelle), nicht das Budget.
            if payload.gremium_id is not None:
                gremium = (
                    await self.session.execute(
                        select(Gremium).where(Gremium.id == payload.gremium_id)
                    )
                ).scalar_one_or_none()
                if gremium is None:
                    raise NotFoundError(f"gremium {payload.gremium_id} not found")
            parent_path = None
            gremium_id = payload.gremium_id
        else:
            parent = await self._get_node(payload.parent_id)
            parent_path = parent.path_key
            gremium_id = parent.gremium_id  # Kinder erben das Gremium des Parents.

        if await self._sibling_exists(payload.parent_id, payload.key):
            raise ConflictError(
                f"budget key {payload.key!r} already exists under this parent"
            )

        node = Budget(
            id=uuid.uuid4(),
            parent_id=payload.parent_id,
            gremium_id=gremium_id,
            key=payload.key,
            path_key=tree_rules.compose_path_key(parent_path, payload.key),
            name=payload.name,
            currency=payload.currency,
            active=payload.active,
            color=payload.color,
        )
        self.session.add(node)
        await self.session.commit()
        return _node_out(node)

    async def _sibling_exists(self, parent_id: UUID | None, key: str) -> bool:
        existing = (
            await self.session.execute(
                select(Budget).where(
                    Budget.parent_id.is_(parent_id) if parent_id is None
                    else Budget.parent_id == parent_id,
                    Budget.key == key,
                )
            )
        ).scalar_one_or_none()
        return existing is not None

    async def update_node(
        self, budget_id: UUID, payload: BudgetNodeUpdate
    ) -> BudgetNodeOut:
        """Name/Aktiv-Status ändern (Key/Parent immutabel → Pfad-Stabilität)."""
        node = await self._get_node(budget_id)
        provided = payload.model_dump(exclude_unset=True)
        for field, value in provided.items():
            setattr(node, field, value)
        await self.session.commit()
        return _node_out(node)

    async def delete_node(self, budget_id: UUID) -> None:
        """Kostenstelle löschen — nur ohne Kinder/Zuteilungen (409 sonst, api.md)."""
        node = await self._get_node(budget_id)
        child = (
            await self.session.execute(
                select(Budget.id).where(Budget.parent_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if child is not None:
            raise ConflictError("budget has child cost-centers; delete them first")
        alloc = (
            await self.session.execute(
                select(BudgetAllocation.id)
                .where(BudgetAllocation.budget_id == budget_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if alloc is not None:
            raise ConflictError("budget has allocations; remove them first")
        await self.session.delete(node)
        await self.session.commit()

    # ----------------------------------------------------------- fiscal years
    async def _require_top_level(self, budget_id: UUID) -> Budget:
        node = await self._get_node(budget_id)
        if node.parent_id is not None:
            raise ValidationProblem(
                "Fiscal years exist only on top-level budgets.",
                errors=[{"field": "budgetId", "msg": "not a top-level budget"}],
            )
        return node

    async def _fiscal_years_of(self, budget_id: UUID) -> list[FiscalYear]:
        return list(
            (
                await self.session.execute(
                    select(FiscalYear)
                    .where(FiscalYear.budget_id == budget_id)
                    .order_by(FiscalYear.start_date)
                )
            ).scalars().all()
        )

    async def list_fiscal_years(self, budget_id: UUID) -> list[FiscalYearOut]:
        await self._require_top_level(budget_id)
        return [_fy_out(f) for f in await self._fiscal_years_of(budget_id)]

    async def list_applications(
        self, budget_id: UUID, fiscal_year_id: UUID | None = None
    ) -> list[BudgetApplicationOut]:
        """Anträge dieser Kostenstelle **und ihres Unterbaums** (#17, Budget-Statistik).

        Unterbaum über das ``path_key``-Präfix (Knoten selbst ``==`` oder Nachfahre
        ``LIKE path||'-%'``). ``stage`` kommt aus dem ``budget_entry`` (1:1 je Antrag),
        optional auf ein Haushaltsjahr gefiltert. Neueste zuerst.
        """
        node = await self._get_node(budget_id)
        subtree = select(Budget.id).where(
            or_(
                Budget.path_key == node.path_key,
                Budget.path_key.like(node.path_key + _SEP + "%"),
            )
        )
        stmt = (
            select(Application, Budget.path_key, BudgetEntry.stage)
            .join(Budget, Budget.id == Application.budget_id)
            .outerjoin(BudgetEntry, BudgetEntry.application_id == Application.id)
            .where(Application.budget_id.in_(subtree))
            .order_by(Application.created_at.desc())
        )
        if fiscal_year_id is not None:
            stmt = stmt.where(Application.fiscal_year_id == fiscal_year_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            BudgetApplicationOut(
                applicationId=app.id,
                title=_title_of(app.data),
                budgetId=app.budget_id,
                pathKey=path_key,
                fiscalYearId=app.fiscal_year_id,
                amount=app.amount,
                currency=app.currency,
                stage=stage,
                stateId=app.current_state_id,
                createdAt=app.created_at,
            )
            for (app, path_key, stage) in rows
        ]

    async def create_fiscal_year(
        self, budget_id: UUID, payload: FiscalYearCreate
    ) -> FiscalYearOut:
        """HHJ anlegen — disjunkt pro Top-Budget (R7.1f/g): 422 bei Überlappung."""
        await self._require_top_level(budget_id)
        if payload.end_date <= payload.start_date:
            raise ValidationProblem(
                "Fiscal year end must be after start.",
                errors=[{"field": "endDate", "msg": "must be after startDate"}],
            )
        existing = [
            (f.start_date, f.end_date) for f in await self._fiscal_years_of(budget_id)
        ]
        if tree_rules.overlaps_any(payload.start_date, payload.end_date, existing):
            raise ValidationProblem(
                "Fiscal year overlaps an existing one (must be disjoint).",
                errors=[{"field": "startDate", "msg": "overlaps another fiscal year"}],
            )
        fy = FiscalYear(
            id=uuid.uuid4(),
            budget_id=budget_id,
            label=payload.label,
            start_date=payload.start_date,
            end_date=payload.end_date,
            active=payload.active,
        )
        self.session.add(fy)
        await self.session.commit()
        return _fy_out(fy)

    async def update_fiscal_year(
        self, budget_id: UUID, fiscal_year_id: UUID, payload: FiscalYearUpdate
    ) -> FiscalYearOut:
        """HHJ ändern; Disjunktheit erneut prüfen (gegen die **anderen** HHJ)."""
        await self._require_top_level(budget_id)
        fy = await self._get_fiscal_year(fiscal_year_id)
        provided = payload.model_dump(exclude_unset=True)
        new_start = provided.get("start_date", fy.start_date)
        new_end = provided.get("end_date", fy.end_date)
        if new_end <= new_start:
            raise ValidationProblem(
                "Fiscal year end must be after start.",
                errors=[{"field": "endDate", "msg": "must be after startDate"}],
            )
        others = [
            (f.start_date, f.end_date)
            for f in await self._fiscal_years_of(budget_id)
            if f.id != fiscal_year_id
        ]
        if tree_rules.overlaps_any(new_start, new_end, others):
            raise ValidationProblem(
                "Fiscal year overlaps an existing one (must be disjoint).",
                errors=[{"field": "startDate", "msg": "overlaps another fiscal year"}],
            )
        for field, value in provided.items():
            setattr(fy, field, value)
        await self.session.commit()
        return _fy_out(fy)

    # ------------------------------------------------------------- allocation
    async def _allocation(
        self, budget_id: UUID, fiscal_year_id: UUID
    ) -> BudgetAllocation | None:
        return (
            await self.session.execute(
                select(BudgetAllocation).where(
                    BudgetAllocation.budget_id == budget_id,
                    BudgetAllocation.fiscal_year_id == fiscal_year_id,
                )
            )
        ).scalar_one_or_none()

    async def _children_alloc_sum(
        self, parent_id: UUID, fiscal_year_id: UUID, *, exclude_id: UUID | None = None
    ) -> Decimal:
        rows = (
            await self.session.execute(
                select(Budget.id, BudgetAllocation.allocated)
                .join(
                    BudgetAllocation,
                    and_(
                        BudgetAllocation.budget_id == Budget.id,
                        BudgetAllocation.fiscal_year_id == fiscal_year_id,
                    ),
                )
                .where(Budget.parent_id == parent_id)
            )
        ).all()
        total = _ZERO
        for child_id, allocated in rows:
            if child_id != exclude_id:
                total += tree_rules.as_amount(allocated)
        return total

    async def set_allocation(
        self, budget_id: UUID, fiscal_year_id: UUID, payload: AllocationSet
    ) -> AllocationOut:
        """Top-Down-Zuteilung setzen (R7.1b). 422 wenn Σ Kinder > Parent (beidseitig)."""
        node = await self._get_node(budget_id)
        fy = await self._get_fiscal_year(fiscal_year_id)
        top = await self._top_level(node)
        if fy.budget_id != top.id:
            raise ValidationProblem(
                "Fiscal year does not belong to this budget's top-level.",
                errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
            )

        # Aufwärts-Constraint: neue Kinder-Summe ≤ Parent-Zuteilung.
        if node.parent_id is not None:
            siblings = await self._children_alloc_sum(
                node.parent_id, fiscal_year_id, exclude_id=node.id
            )
            parent_alloc = await self._allocation(node.parent_id, fiscal_year_id)
            parent_value = parent_alloc.allocated if parent_alloc is not None else None
            if tree_rules.children_allocation_exceeds_parent(
                parent_value, siblings, payload.allocated
            ):
                raise ValidationProblem(
                    "Children allocation would exceed the parent budget.",
                    errors=[{"field": "allocated", "msg": "exceeds parent budget"}],
                )

        # Abwärts-Constraint: Zuteilung nicht unter bereits verteilte Kinder-Summe.
        own_children = await self._children_alloc_sum(node.id, fiscal_year_id)
        if tree_rules.parent_allocation_below_children(payload.allocated, own_children):
            raise ValidationProblem(
                "Allocation is below the sum already distributed to children.",
                errors=[{"field": "allocated", "msg": "below children allocations"}],
            )

        alloc = await self._allocation(budget_id, fiscal_year_id)
        if alloc is None:
            alloc = BudgetAllocation(
                id=uuid.uuid4(),
                budget_id=budget_id,
                fiscal_year_id=fiscal_year_id,
            )
            self.session.add(alloc)
        alloc.allocated = payload.allocated
        await self.session.commit()
        return AllocationOut(
            budgetId=budget_id,
            fiscalYearId=fiscal_year_id,
            allocated=payload.allocated,
        )

    # ----------------------------------------------------------- assignment
    async def assign_budget(
        self, application_id: UUID, payload: AssignBudgetRequest
    ) -> AssignBudgetOut:
        """Antrag einer Kostenstelle zuordnen; HHJ aus aktivem HHJ des Top-Budgets (R7.1e).

        ``budgetId=null`` löst die Zuordnung (auch ``fiscalYearId`` → null).
        """
        app = await self._get_application(application_id)
        if payload.budget_id is None:
            app.budget_id = None
            app.fiscal_year_id = None
            await self.session.commit()
            return AssignBudgetOut(
                applicationId=app.id, budgetId=None, fiscalYearId=None
            )

        node = await self._get_node(payload.budget_id)
        top = await self._top_level(node)
        active_ids = [
            f.id for f in await self._fiscal_years_of(top.id) if f.active
        ]
        fy_id = tree_rules.pick_fiscal_year(active_ids)
        app.budget_id = node.id
        app.fiscal_year_id = fy_id
        await self.session.commit()
        return AssignBudgetOut(
            applicationId=app.id, budgetId=node.id, fiscalYearId=fy_id
        )

    async def move_fiscal_year(
        self, application_id: UUID, payload: MoveFiscalYearRequest
    ) -> AssignBudgetOut:
        """Antrag in anderes HHJ verschieben (R7.1e). HHJ muss zum Top-Budget passen."""
        app = await self._get_application(application_id)
        if app.budget_id is None:
            raise ValidationProblem(
                "Application has no budget assignment.",
                errors=[{"field": "budgetId", "msg": "assign a cost-center first"}],
            )
        node = await self._get_node(app.budget_id)
        top = await self._top_level(node)
        fy = await self._get_fiscal_year(payload.fiscal_year_id)
        if fy.budget_id != top.id:
            raise ValidationProblem(
                "Fiscal year does not belong to this application's top-level budget.",
                errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
            )
        app.fiscal_year_id = fy.id
        await self.session.commit()
        return AssignBudgetOut(
            applicationId=app.id, budgetId=app.budget_id, fiscalYearId=fy.id
        )

    # --------------------------------------------------------------- expenses
    async def _resolve_expense_fiscal_year(
        self, node: Budget, fiscal_year_id: UUID | None
    ) -> UUID:
        """HHJ einer Ausgabe bestimmen: explizit (muss zum Top-Budget gehören) oder
        — falls offen — das **eine** aktive HHJ des Top-Budgets (sonst 422)."""
        top = await self._top_level(node)
        if fiscal_year_id is not None:
            fy = await self._get_fiscal_year(fiscal_year_id)
            if fy.budget_id != top.id:
                raise ValidationProblem(
                    "Fiscal year does not belong to this budget's top-level.",
                    errors=[{"field": "fiscalYearId", "msg": "wrong top-level budget"}],
                )
            return fy.id
        active_ids = [f.id for f in await self._fiscal_years_of(top.id) if f.active]
        picked = tree_rules.pick_fiscal_year(active_ids)
        if picked is None:
            raise ValidationProblem(
                "No single active fiscal year — specify fiscalYearId.",
                errors=[{"field": "fiscalYearId", "msg": "ambiguous or missing"}],
            )
        return picked

    async def create_expense(
        self, budget_id: UUID, payload: ExpenseCreate, *, actor: str
    ) -> ExpenseOut:
        """Eigenständige Ausgabe gegen eine Kostenstelle buchen (#25, ohne Antrag)."""
        node = await self._get_node(budget_id)
        fy_id = await self._resolve_expense_fiscal_year(node, payload.fiscal_year_id)
        expense = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=node.id,
            fiscal_year_id=fy_id,
            amount=payload.amount,
            currency=node.currency,
            description=payload.description,
            actor=actor,
        )
        self.session.add(expense)
        await self.session.commit()
        return ExpenseOut(
            id=expense.id,
            budgetId=node.id,
            pathKey=node.path_key,
            fiscalYearId=fy_id,
            amount=expense.amount,
            currency=expense.currency,
            description=expense.description,
            actor=expense.actor,
            createdAt=expense.created_at,
        )

    async def list_expenses(
        self, budget_id: UUID, fiscal_year_id: UUID | None = None
    ) -> list[ExpenseOut]:
        """Ausgaben dieser Kostenstelle **und ihres Unterbaums** (#25, optional HHJ)."""
        node = await self._get_node(budget_id)
        subtree = select(Budget.id).where(
            or_(
                Budget.path_key == node.path_key,
                Budget.path_key.like(node.path_key + _SEP + "%"),
            )
        )
        stmt = (
            select(BudgetExpense, Budget.path_key)
            .join(Budget, Budget.id == BudgetExpense.budget_id)
            .where(BudgetExpense.budget_id.in_(subtree))
            .order_by(BudgetExpense.created_at.desc())
        )
        if fiscal_year_id is not None:
            stmt = stmt.where(BudgetExpense.fiscal_year_id == fiscal_year_id)
        rows = (await self.session.execute(stmt)).all()
        return [
            ExpenseOut(
                id=e.id,
                budgetId=e.budget_id,
                pathKey=path_key,
                fiscalYearId=e.fiscal_year_id,
                amount=e.amount,
                currency=e.currency,
                description=e.description,
                actor=e.actor,
                createdAt=e.created_at,
            )
            for (e, path_key) in rows
        ]

    async def delete_expense(self, expense_id: UUID) -> None:
        """Ausgabe löschen (#25)."""
        expense = (
            await self.session.execute(
                select(BudgetExpense).where(BudgetExpense.id == expense_id)
            )
        ).scalar_one_or_none()
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        await self.session.delete(expense)
        await self.session.commit()

    # --------------------------------------------------------------- tree view
    async def get_tree(
        self, *, gremium_id: UUID | None = None
    ) -> list[BudgetTreeNodeOut]:
        """Kostenstellen-Baum mit allocated/committed/beantragt/available je HHJ (R7.4).

        Klassifikation per Top-Budget (#budget-redesign): ein Antrag zählt als
        **gebunden** (committed), wenn sein aktueller Flow-State-Key in den
        ``accepted_state_keys`` des Top-Budgets liegt; als **beantragt** (requested),
        wenn er weder accepted noch denied ist; denied wird ausgeschlossen."""
        nodes = (
            await self.session.execute(
                select(Budget).order_by(Budget.path_key)
            )
        ).scalars().all()
        allocs = (
            await self.session.execute(select(BudgetAllocation))
        ).scalars().all()
        # Anträge mit Kostenstelle + HHJ + aktuellem Flow-State-Key.
        app_rows = (
            await self.session.execute(
                select(
                    Budget.path_key,
                    Application.fiscal_year_id,
                    Application.amount,
                    State.key,
                )
                .join(Application, Application.budget_id == Budget.id)
                .join(State, State.id == Application.current_state_id)
                .where(
                    Application.amount.is_not(None),
                    Application.fiscal_year_id.is_not(None),
                )
            )
        ).all()

        # Eigenständige Ausgaben (#25) zählen immer als gebundener Verbrauch.
        expense_rows = (
            await self.session.execute(
                select(
                    Budget.path_key,
                    BudgetExpense.fiscal_year_id,
                    BudgetExpense.amount,
                ).join(Budget, Budget.id == BudgetExpense.budget_id)
            )
        ).all()

        # Top-Budget-Config: erstes Pfad-Segment → (accepted, denied) State-Keys.
        top_config: dict[str, tuple[set[str], set[str]]] = {
            n.path_key: (set(n.accepted_state_keys or []), set(n.denied_state_keys or []))
            for n in nodes
            if n.parent_id is None
        }

        committed_rows: list[tuple[object, str, Decimal | None]] = []
        requested_rows: list[tuple[object, str, Decimal | None]] = []
        for path, fy, amount, state_key in app_rows:
            accepted, denied = top_config.get(path.split("-")[0], (set(), set()))
            if state_key in accepted:
                committed_rows.append((fy, path, amount))
            elif state_key in denied:
                continue  # ausgeschlossen
            else:
                requested_rows.append((fy, path, amount))
        committed_rows += [(fy, path, amount) for path, fy, amount in expense_rows]

        node_tuples = [
            (
                n.id, n.parent_id, n.gremium_id, n.key, n.path_key, n.name,
                n.currency, n.active, n.color,
                list(n.accepted_state_keys or []), list(n.denied_state_keys or []),
            )
            for n in nodes
        ]
        alloc_tuples = [(a.budget_id, a.fiscal_year_id, a.allocated) for a in allocs]
        forest = tree_rules.build_forest(
            node_tuples, alloc_tuples, committed_rows, requested_rows, gremium_id=gremium_id
        )
        return [BudgetTreeNodeOut.model_validate(d) for d in forest]
