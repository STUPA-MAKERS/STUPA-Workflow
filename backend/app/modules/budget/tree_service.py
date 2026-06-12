"""Budget-Baum-Service (CR #76/#78): Kostenstellen-CRUD, Haushaltsjahre, Top-Down-
Zuteilung, Antrag→Kostenstelle/HHJ-Zuordnung, Baum-Sicht mit Roll-up.

Dünne I/O-Verdrahtung; alle Entscheidungen liegen in :mod:`app.modules.budget.tree_rules`
(testing.md §1: ``budget`` = kritisches Modul, 100 % Branch). problem+json bei Fehlern.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.applications.service import _title_of
from app.modules.budget import tree_rules
from app.modules.budget.models import BudgetEntry
from app.modules.budget.tree_models import (
    Account,
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountOut,
    AccountUpdate,
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
    ExpenseUpdate,
    FiscalYearCreate,
    FiscalYearOut,
    FiscalYearUpdate,
    MoveFiscalYearRequest,
    TransferCreate,
    TransferOut,
)
from app.modules.flow.models import State
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from app.shared.paging import Page

_ZERO = Decimal("0")


def _natural_path_key(path_key: str) -> tuple:
    """Natürliche Sortierung des Pfads: numerische Segmente als Zahl (``VSM-10``
    nach ``VSM-9``), nicht-numerische als String. Tupel-Vergleich ist typrein, da
    sich numerische ``(0, int)`` und String-Segmente ``(1, str)`` an Position 0
    unterscheiden. Präfix-Pfade (Eltern) sortieren vor ihren Erweiterungen."""
    return tuple(
        (0, int(s)) if s.isdigit() else (1, s) for s in path_key.split("-")
    )


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
        fullyBound=b.fully_bound,
        hiddenInBudget=bool(b.hidden_in_budget),
        viewGremiumId=b.view_gremium_id,
        fiscalStartMonth=b.fiscal_start_month,
        fiscalStartDay=b.fiscal_start_day,
    )


def _fy_out(f: FiscalYear, start_month: int, start_day: int) -> FiscalYearOut:
    return FiscalYearOut(
        id=f.id,
        budgetId=f.budget_id,
        year=f.year,
        display=tree_rules.fiscal_year_display(f.year, start_month, start_day),
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
            fully_bound=False,
            # Stichtag nur am Top-Level fachlich relevant (Kinder bleiben beim Default).
            fiscal_start_month=payload.fiscal_start_month,
            fiscal_start_day=payload.fiscal_start_day,
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
        """Name/Aktiv-Status/Stichtag/**Key** ändern (Parent immutabel → Baum-Stabilität).

        Wird der ``key`` geändert, leitet sich der ``path_key`` des Knotens **und aller
        Nachfahren** neu ab (alles referenziert ``budget_id``, nicht den Pfad). Ändert
        sich der HHJ-Stichtag eines Top-Budgets, leiten sich die Start-/End-Daten aller
        bestehenden HHJ neu daraus ab (Jahr bleibt, Datum folgt)."""
        node = await self._get_node(budget_id)
        provided = payload.model_dump(exclude_unset=True)
        new_key = provided.pop("key", None)
        stichtag_changed = (
            ("fiscal_start_month" in provided
             and provided["fiscal_start_month"] != node.fiscal_start_month)
            or ("fiscal_start_day" in provided
                and provided["fiscal_start_day"] != node.fiscal_start_day)
        )
        for field, value in provided.items():
            setattr(node, field, value)
        if new_key is not None and new_key != node.key:
            await self._rename_key(node, new_key)
        if stichtag_changed and node.parent_id is None:
            for fy in await self._fiscal_years_of(budget_id):
                fy.start_date, fy.end_date = tree_rules.fiscal_year_bounds(
                    fy.year, node.fiscal_start_month, node.fiscal_start_day
                )
        await self.session.commit()
        return _node_out(node)

    async def _rename_key(self, node: Budget, new_key: str) -> None:
        """``key`` einer Kostenstelle ändern → ``path_key`` von Knoten + Nachfahren neu.

        Pfad-Segment muss gültig + unter dem Parent eindeutig sein (sonst 422/409)."""
        if not tree_rules.is_valid_key(new_key):
            raise ValidationProblem(
                "Invalid budget key.",
                errors=[{"field": "key", "msg": "must be alphanumeric (no '-')"}],
            )
        if await self._sibling_exists(node.parent_id, new_key):
            raise ConflictError(
                f"budget key {new_key!r} already exists under this parent"
            )
        parent_path: str | None = None
        if node.parent_id is not None:
            parent_path = (await self._get_node(node.parent_id)).path_key
        old_path = node.path_key
        new_path = tree_rules.compose_path_key(parent_path, new_key)
        # Nachfahren (Pfad-Präfix) holen, bevor der Knoten umbenannt wird.
        descendants = (
            await self.session.execute(
                select(Budget).where(Budget.path_key.like(old_path + _SEP + "%"))
            )
        ).scalars().all()
        node.key = new_key
        node.path_key = new_path
        for d in descendants:
            d.path_key = new_path + d.path_key[len(old_path):]

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
                    .order_by(FiscalYear.year)
                )
            ).scalars().all()
        )

    async def list_fiscal_years(self, budget_id: UUID) -> list[FiscalYearOut]:
        """HHJ-Liste — für JEDEN Knoten: Nicht-Top-Level löst auf seinen Top-Level-
        Vorfahren auf (#budget-scope: gescopte Roots sind oft Unter-Kostenstellen)."""
        node = await self._get_node(budget_id)
        top = node
        while top.parent_id is not None:
            top = await self._get_node(top.parent_id)
        return [
            _fy_out(f, top.fiscal_start_month, top.fiscal_start_day)
            for f in await self._fiscal_years_of(top.id)
        ]

    async def can_view_node(
        self, budget_id: UUID, member_gremium_ids: set[UUID]
    ) -> bool:
        """Knoten für ein Gremium-Mitglied sichtbar (#budget-scope)? Wahr, wenn der
        Knoten SELBST oder ein VORFAHRE einem der Mitglieds-Gremien zugeordnet ist."""
        if not member_gremium_ids:
            return False
        node = await self._get_node(budget_id)
        segments = node.path_key.split(_SEP)
        prefixes = [_SEP.join(segments[: i + 1]) for i in range(len(segments))]
        rows = (
            await self.session.execute(
                select(Budget.view_gremium_id).where(Budget.path_key.in_(prefixes))
            )
        ).scalars()
        return any(v in member_gremium_ids for v in rows if v is not None)

    async def fiscal_year_label_map(self) -> dict[UUID, str]:
        """``fiscal_year_id`` → Anzeige (``YYYY``/``YYYY/YY``) über alle Top-Budgets."""
        rows = (
            await self.session.execute(
                select(
                    FiscalYear.id,
                    FiscalYear.year,
                    Budget.fiscal_start_month,
                    Budget.fiscal_start_day,
                ).join(Budget, Budget.id == FiscalYear.budget_id)
            )
        ).all()
        return {
            fid: tree_rules.fiscal_year_display(year, month, day)
            for fid, year, month, day in rows
        }

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
            select(
                Application,
                Budget.path_key,
                BudgetEntry.stage,
                State.label_i18n,
                State.color,
            )
            .join(Budget, Budget.id == Application.budget_id)
            .outerjoin(BudgetEntry, BudgetEntry.application_id == Application.id)
            .outerjoin(State, State.id == Application.current_state_id)
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
                stateLabel=state_label or None,
                stateColor=state_color,
                createdAt=app.created_at,
            )
            for (app, path_key, stage, state_label, state_color) in rows
        ]

    async def create_fiscal_year(
        self, budget_id: UUID, payload: FiscalYearCreate
    ) -> FiscalYearOut:
        """HHJ (Jahr) anlegen — Start/Ende aus Budget-Stichtag; eindeutig pro Top-Budget."""
        top = await self._require_top_level(budget_id)
        start, end = tree_rules.fiscal_year_bounds(
            payload.year, top.fiscal_start_month, top.fiscal_start_day
        )
        existing = await self._fiscal_years_of(budget_id)
        if any(f.year == payload.year for f in existing):
            raise ValidationProblem(
                "Fiscal year already exists for this budget.",
                errors=[{"field": "year", "msg": "fiscal year already exists"}],
            )
        fy = FiscalYear(
            id=uuid.uuid4(),
            budget_id=budget_id,
            year=payload.year,
            start_date=start,
            end_date=end,
            active=payload.active,
        )
        self.session.add(fy)
        await self.session.commit()
        return _fy_out(fy, top.fiscal_start_month, top.fiscal_start_day)

    async def update_fiscal_year(
        self, budget_id: UUID, fiscal_year_id: UUID, payload: FiscalYearUpdate
    ) -> FiscalYearOut:
        """HHJ ändern (Jahr und/oder Aktiv-Status); Jahr eindeutig pro Top-Budget."""
        top = await self._require_top_level(budget_id)
        fy = await self._get_fiscal_year(fiscal_year_id)
        provided = payload.model_dump(exclude_unset=True)
        new_year = provided.get("year", fy.year)
        if new_year != fy.year and any(
            f.year == new_year and f.id != fiscal_year_id
            for f in await self._fiscal_years_of(budget_id)
        ):
            raise ValidationProblem(
                "Fiscal year already exists for this budget.",
                errors=[{"field": "year", "msg": "fiscal year already exists"}],
            )
        if "year" in provided:
            fy.year = new_year
            fy.start_date, fy.end_date = tree_rules.fiscal_year_bounds(
                new_year, top.fiscal_start_month, top.fiscal_start_day
            )
        if "active" in provided:
            fy.active = provided["active"]
        await self.session.commit()
        return _fy_out(fy, top.fiscal_start_month, top.fiscal_start_day)

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

    @staticmethod
    def _expense_out(
        e: BudgetExpense,
        path_key: str | None,
        app_title: str | None = None,
        account_name: str | None = None,
    ) -> ExpenseOut:
        return ExpenseOut(
            id=e.id,
            budgetId=e.budget_id,
            pathKey=path_key,
            fiscalYearId=e.fiscal_year_id,
            kind=e.kind,  # type: ignore[arg-type]
            amount=e.amount,
            currency=e.currency,
            description=e.description,
            applicationId=e.application_id,
            applicationTitle=app_title,
            accountId=e.account_id,
            accountName=account_name,
            transferId=e.transfer_id,
            actor=e.actor,
            createdAt=e.created_at,
        )

    async def create_expense(
        self, budget_id: UUID, payload: ExpenseCreate, *, actor: str
    ) -> ExpenseOut:
        """(Kompat) Buchung gegen die Kostenstelle aus dem Pfad (``/budgets/{id}``)."""
        return await self.book_expense(
            payload.model_copy(update={"budget_id": budget_id}), actor=actor
        )

    async def book_expense(self, payload: ExpenseCreate, *, actor: str) -> ExpenseOut:
        """Ausgabe/Einnahme buchen (#25).

        Gebunden (``applicationId`` gesetzt) erbt Kostenstelle + HHJ vom Antrag;
        eigenständig braucht ``budgetId`` (HHJ ggf. automatisch aufgelöst).
        """
        app_title: str | None = None
        if payload.application_id is not None:
            app = await self.session.get(Application, payload.application_id)
            if app is None:
                raise NotFoundError(f"application {payload.application_id} not found")
            if app.budget_id is None or app.fiscal_year_id is None:
                raise ValidationProblem(
                    "Application has no budget/fiscal year assigned.",
                    errors=[{"field": "applicationId", "msg": "no budget assigned"}],
                )
            node = await self._get_node(app.budget_id)
            fy_id = app.fiscal_year_id
            app_title = _title_of(app.data)
        else:
            if payload.budget_id is None:
                raise ValidationProblem(
                    "budgetId is required for a standalone booking.",
                    errors=[{"field": "budgetId", "msg": "required"}],
                )
            node = await self._get_node(payload.budget_id)
            fy_id = await self._resolve_expense_fiscal_year(node, payload.fiscal_year_id)
        account_name = await self._validate_account(payload.account_id)
        expense = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=node.id,
            fiscal_year_id=fy_id,
            application_id=payload.application_id,
            account_id=payload.account_id,
            kind=payload.kind,
            amount=payload.amount,
            currency=node.currency,
            description=payload.description,
            actor=actor,
        )
        self.session.add(expense)
        await self.session.commit()
        return self._expense_out(expense, node.path_key, app_title, account_name)

    async def _validate_account(self, account_id: UUID | None) -> str | None:
        """Konto prüfen (falls angegeben) → Name; sonst ``None``."""
        if account_id is None:
            return None
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        return acc.name

    async def update_expense(
        self, expense_id: UUID, payload: ExpenseUpdate
    ) -> ExpenseOut:
        """Betrag/Beschreibung einer Buchung ändern (#25). HHJ/Kostenstelle/Bindung fix."""
        expense = await self.session.get(BudgetExpense, expense_id)
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        if payload.amount is not None:
            expense.amount = payload.amount
        if payload.description is not None:
            expense.description = payload.description
        await self.session.commit()
        node = await self._get_node(expense.budget_id)
        app_title: str | None = None
        if expense.application_id is not None:
            app = await self.session.get(Application, expense.application_id)
            app_title = _title_of(app.data) if app is not None else None
        acc_name = (
            (await self.session.get(Account, expense.account_id)).name  # type: ignore[union-attr]
            if expense.account_id is not None
            else None
        )
        return self._expense_out(expense, node.path_key, app_title, acc_name)

    async def list_expenses(
        self, budget_id: UUID, fiscal_year_id: UUID | None = None
    ) -> list[ExpenseOut]:
        """(Kompat) Buchungen dieser Kostenstelle + Unterbaum (#25, optional HHJ)."""
        page = await self.list_expenses_paged(
            budget_id=budget_id, fiscal_year_id=fiscal_year_id, limit=10_000, offset=0
        )
        return page.items

    async def list_expenses_paged(
        self,
        *,
        budget_id: UUID | None = None,
        fiscal_year_id: UUID | None = None,
        kind: str | None = None,
        application_id: UUID | None = None,
        q: str | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[ExpenseOut]:
        """Buchungen (Ausgaben/Einnahmen) gefiltert + offset-paginiert (#25).

        ``budget_id`` schränkt auf die Kostenstelle **und ihren Unterbaum** ein.
        """
        filters = []
        if budget_id is not None:
            node = await self._get_node(budget_id)
            subtree = select(Budget.id).where(
                or_(
                    Budget.path_key == node.path_key,
                    Budget.path_key.like(node.path_key + _SEP + "%"),
                )
            )
            filters.append(BudgetExpense.budget_id.in_(subtree))
        if fiscal_year_id is not None:
            filters.append(BudgetExpense.fiscal_year_id == fiscal_year_id)
        if kind is not None:
            filters.append(BudgetExpense.kind == kind)
        if application_id is not None:
            filters.append(BudgetExpense.application_id == application_id)
        if q:
            filters.append(BudgetExpense.description.ilike(f"%{q}%"))
        if amount_min is not None:
            filters.append(BudgetExpense.amount >= amount_min)
        if amount_max is not None:
            filters.append(BudgetExpense.amount <= amount_max)
        if created_from:
            filters.append(func.date(BudgetExpense.created_at) >= created_from)
        if created_to:
            filters.append(func.date(BudgetExpense.created_at) <= created_to)

        # Sortier-Spalte (whitelist) + Richtung; Default: neueste zuerst.
        sort_col = BudgetExpense.amount if sort == "amount" else BudgetExpense.created_at
        ordering = sort_col.asc() if order == "asc" else sort_col.desc()

        total = await self.session.scalar(
            select(func.count()).select_from(BudgetExpense).where(*filters)
        )
        rows = (
            await self.session.execute(
                select(BudgetExpense, Budget.path_key, Application.data, Account.name)
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .outerjoin(Application, Application.id == BudgetExpense.application_id)
                .outerjoin(Account, Account.id == BudgetExpense.account_id)
                .where(*filters)
                .order_by(ordering, BudgetExpense.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        items = [
            self._expense_out(e, path_key, _title_of(data) if data else None, acc_name)
            for (e, path_key, data, acc_name) in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def delete_expense(self, expense_id: UUID) -> None:
        """Ausgabe löschen (#25). Teil eines Übertrags → beide Buchungen löschen."""
        expense = (
            await self.session.execute(
                select(BudgetExpense).where(BudgetExpense.id == expense_id)
            )
        ).scalar_one_or_none()
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        if expense.transfer_id is not None:
            pair = (
                await self.session.execute(
                    select(BudgetExpense).where(
                        BudgetExpense.transfer_id == expense.transfer_id
                    )
                )
            ).scalars().all()
            for e in pair:
                await self.session.delete(e)
        else:
            await self.session.delete(expense)
        await self.session.commit()

    # --------------------------------------------------------------- accounts
    @staticmethod
    def _account_out(a: Account) -> AccountOut:
        return AccountOut(id=a.id, name=a.name, iban=a.iban, active=a.active)

    async def list_accounts(self) -> list[AccountOut]:
        rows = (
            await self.session.scalars(select(Account).order_by(Account.name))
        ).all()
        return [self._account_out(a) for a in rows]

    async def create_account(self, payload: AccountCreate) -> AccountOut:
        acc = Account(
            id=uuid.uuid4(), name=payload.name, iban=payload.iban, active=payload.active
        )
        self.session.add(acc)
        await self.session.commit()
        return self._account_out(acc)

    async def update_account(
        self, account_id: UUID, payload: AccountUpdate
    ) -> AccountOut:
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(acc, field, value)
        await self.session.commit()
        return self._account_out(acc)

    async def delete_account(self, account_id: UUID) -> None:
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        await self.session.delete(acc)  # Buchungen behalten account_id=NULL (SET NULL).
        await self.session.commit()

    # --------------------------------------------------------------- transfer
    async def create_transfer(
        self, payload: TransferCreate, *, actor: str
    ) -> TransferOut:
        """Übertrag KS→KS: Ausgabe auf Quelle + Einnahme auf Ziel (gleiches HHJ)."""
        src = await self._get_node(payload.from_budget_id)
        dst = await self._get_node(payload.to_budget_id)
        # HHJ muss zum Top-Level **beider** Kostenstellen gehören (gleiches HHJ).
        fy_src = await self._resolve_expense_fiscal_year(src, payload.fiscal_year_id)
        fy_dst = await self._resolve_expense_fiscal_year(dst, payload.fiscal_year_id)
        if fy_src != fy_dst:
            raise ValidationProblem(
                "Both cost centres must share the fiscal year.",
                errors=[{"field": "fiscalYearId", "msg": "must match for both"}],
            )
        transfer_id = uuid.uuid4()
        out_row = BudgetExpense(
            id=uuid.uuid4(), budget_id=src.id, fiscal_year_id=fy_src,
            transfer_id=transfer_id, kind="expense", amount=payload.amount,
            currency=src.currency, description=payload.description, actor=actor,
        )
        in_row = BudgetExpense(
            id=uuid.uuid4(), budget_id=dst.id, fiscal_year_id=fy_dst,
            transfer_id=transfer_id, kind="income", amount=payload.amount,
            currency=dst.currency, description=payload.description, actor=actor,
        )
        self.session.add_all([out_row, in_row])
        await self.session.commit()
        return TransferOut(
            transferId=transfer_id, expenseId=out_row.id, incomeId=in_row.id
        )

    # --------------------------------------------------------------- tree view
    async def get_tree(
        self,
        *,
        gremium_id: UUID | None = None,
        visible_gremium_ids: set[UUID] | None = None,
    ) -> list[BudgetTreeNodeOut]:
        """Kostenstellen-Baum mit allocated/committed/beantragt/available je HHJ (R7.4).

        Klassifikation per Top-Budget (#budget-redesign): ein Antrag zählt als
        **gebunden** (committed), wenn sein aktueller Flow-State-Key in den
        ``accepted_state_keys`` des Top-Budgets liegt; als **beantragt** (requested),
        wenn er weder accepted noch denied ist; denied wird ausgeschlossen."""
        nodes = list(
            (await self.session.execute(select(Budget))).scalars().all()
        )
        # Natürliche Reihenfolge (VSM-10 nach VSM-9 statt lexikografisch); Eltern vor
        # Kindern bleibt erhalten → build_forest erbt die Geschwister-Reihenfolge.
        nodes.sort(key=lambda b: _natural_path_key(b.path_key))
        allocs = (
            await self.session.execute(select(BudgetAllocation))
        ).scalars().all()
        # Anträge mit Kostenstelle + HHJ + aktuellem Flow-State-Key.
        app_rows = (
            await self.session.execute(
                select(
                    Application.id,
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

        # Ausgaben/Einnahmen (#25): tatsächlicher Verbrauch (expended) bzw. Einnahmen
        # (income). Antrags-gebundene Ausgaben tragen ``application_id`` → sie ersetzen
        # den gebundenen Betrag des Antrags anteilig.
        expense_rows = (
            await self.session.execute(
                select(
                    Budget.path_key,
                    BudgetExpense.fiscal_year_id,
                    BudgetExpense.amount,
                    BudgetExpense.kind,
                    BudgetExpense.application_id,
                ).join(Budget, Budget.id == BudgetExpense.budget_id)
            )
        ).all()

        # Σ an einen Antrag gebundene **Ausgaben** (income mindert die Bindung nicht).
        spent_per_app: dict[object, Decimal] = {}
        for _path, _fy, amount, kind, app_id in expense_rows:
            if kind == "expense" and app_id is not None:
                spent_per_app[app_id] = spent_per_app.get(app_id, _ZERO) + (
                    amount or _ZERO
                )

        # Top-Budget-Config: erstes Pfad-Segment → (accepted, denied) State-Keys.
        top_config: dict[str, tuple[set[str], set[str]]] = {
            n.path_key: (set(n.accepted_state_keys or []), set(n.denied_state_keys or []))
            for n in nodes
            if n.parent_id is None
        }

        # »Komplett gebunden«: Kostenstellen, deren gesamte Zuteilung je HHJ als gebunden
        # zählt. Echte Anträge/Ausgaben unter einem solchen Knoten (er selbst + Unterbaum)
        # werden NICHT zusätzlich gezählt; stattdessen wird die Zuteilung als gebunden
        # injiziert (rollt zum Parent hoch).
        flagged_paths = sorted(n.path_key for n in nodes if n.fully_bound)

        def _under_flagged(path: str) -> bool:
            return any(
                path == fp or path.startswith(fp + _SEP) for fp in flagged_paths
            )

        bound_rows: list[tuple[object, str, Decimal | None]] = []
        requested_rows: list[tuple[object, str, Decimal | None]] = []
        for app_id, path, fy, amount, state_key in app_rows:
            if _under_flagged(path):
                continue  # voll gebunden → echte Anträge ignorieren
            accepted, denied = top_config.get(path.split("-")[0], (set(), set()))
            if state_key in accepted:
                # Bindung anteilig um bereits gebundene Ausgaben mindern (#25).
                spent = spent_per_app.get(app_id, _ZERO)
                remaining = (amount or _ZERO) - spent
                if remaining > _ZERO:
                    bound_rows.append((fy, path, remaining))
            elif state_key in denied:
                continue  # ausgeschlossen
            else:
                # Auch beantragte (in-flight) Anträge anteilig um bereits gebuchte
                # Ausgaben mindern — die Ausgabe zählt als ausgegeben, nicht doppelt (#25).
                spent = spent_per_app.get(app_id, _ZERO)
                remaining = (amount or _ZERO) - spent
                if remaining > _ZERO:
                    requested_rows.append((fy, path, remaining))

        expended_rows = [
            (fy, path, amount)
            for path, fy, amount, kind, _app in expense_rows
            if kind == "expense" and not _under_flagged(path)
        ]
        income_rows = [
            (fy, path, amount)
            for path, fy, amount, kind, _app in expense_rows
            if kind == "income" and not _under_flagged(path)
        ]

        # Synthetische Bindung: ganze Zuteilung der markierten Kostenstelle = gebunden.
        flagged_ids = {n.id for n in nodes if n.fully_bound}
        path_by_id = {n.id: n.path_key for n in nodes}
        for a in allocs:
            if a.budget_id in flagged_ids and a.allocated:
                bound_rows.append((a.fiscal_year_id, path_by_id[a.budget_id], a.allocated))

        node_tuples = [
            (
                n.id, n.parent_id, n.gremium_id, n.key, n.path_key, n.name,
                n.currency, n.active, n.color,
                list(n.accepted_state_keys or []), list(n.denied_state_keys or []),
                n.fiscal_start_month, n.fiscal_start_day, n.fully_bound,
                bool(n.hidden_in_budget), n.view_gremium_id,
            )
            for n in nodes
        ]
        alloc_tuples = [(a.budget_id, a.fiscal_year_id, a.allocated) for a in allocs]
        forest = tree_rules.build_forest(
            node_tuples,
            alloc_tuples,
            bound_rows,
            requested_rows,
            expended_rows,
            income_rows,
            gremium_id=gremium_id,
        )
        # Gremium-Scope (#budget-scope): ohne globale budget.*-Permission werden nur
        # die zugeordneten Teilbäume (view_gremium_id ∈ Mitglieds-Gremien) zu Roots.
        if visible_gremium_ids is not None:
            forest = tree_rules.scope_forest(forest, set(visible_gremium_ids))
        return [BudgetTreeNodeOut.model_validate(d) for d in forest]
