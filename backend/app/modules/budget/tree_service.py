"""Budget-Baum-Service (CR #76/#78): Kostenstellen-CRUD, Haushaltsjahre, Top-Down-
Zuteilung, Antrag→Kostenstelle/HHJ-Zuordnung, Baum-Sicht mit Roll-up.

Dünne I/O-Verdrahtung; alle Entscheidungen liegen in :mod:`app.modules.budget.tree_rules`
(testing.md §1: ``budget`` = kritisches Modul, 100 % Branch). problem+json bei Fehlern.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Text as _Text
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.applications.service import _title_of
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget import tree_rules
from app.modules.budget.invoice_import import parse_zugferd_pdf
from app.modules.budget.models import BudgetEntry
from app.modules.budget.tree_models import (
    Account,
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
    Invoice,
)
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountOption,
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
    InvoiceCreate,
    InvoiceFileResult,
    InvoiceOut,
    InvoiceParseResult,
    InvoiceUpdate,
    MoveFiscalYearRequest,
    TransferCreate,
    TransferOut,
)
from app.modules.files.mime import MimeRejected, sanitize_filename, validate_upload
from app.modules.files.scanner import ScannerError, build_scanner
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.flow.models import State
from app.search import dialect_of, trigram_rank
from app.settings import Settings, get_settings
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from app.shared.paging import Page

logger = logging.getLogger("app.budget")

_ZERO = Decimal("0")

# Beleg-Tokens (#15) sind immer server-erzeugte Keys unter diesem Prefix; alles
# andere weisen wir ab, damit ein Client den ``fileObjectKey`` nicht auf ein
# fremdes Bucket-Objekt zeigen lassen kann.
_INVOICE_FILE_PREFIX = "invoices/"


def _validate_invoice_file_token(token: str) -> str:
    if not token.startswith(_INVOICE_FILE_PREFIX) or ".." in token:
        raise ValidationProblem("invalid invoice file token")
    return token


def _natural_path_key(path_key: str) -> tuple:
    """Natürliche Sortierung des Pfads: numerische Segmente als Zahl (``VSM-10``
    nach ``VSM-9``), nicht-numerische als String. Tupel-Vergleich ist typrein, da
    sich numerische ``(0, int)`` und String-Segmente ``(1, str)`` an Position 0
    unterscheiden. Präfix-Pfade (Eltern) sortieren vor ihren Erweiterungen."""
    return tuple((0, int(s)) if s.isdigit() else (1, s) for s in path_key.split("-"))


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

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        settings: Settings | None = None,
        actor: str | None = None,
    ) -> None:
        self.session = session
        # Storage/Settings nur für den Rechnungs-Import (#15) nötig; die übrigen
        # Budget-Endpunkte verdrahten sie nicht (bleiben ``None``).
        self.storage = storage
        self.settings = settings or get_settings()
        # Principal-``sub`` für den Audit-Trail der Geld-Mutationen (#sec-audit). Der
        # Router setzt ihn; direkte (Test-)Instanzen ohne Akteur loggen ``actor=None``.
        self.actor = actor

    async def _audit(
        self,
        action: AuditAction,
        *,
        target_type: str,
        target_id: str,
        data: dict | None = None,
    ) -> None:
        """Audit-Eintrag in der **laufenden** Transaktion (vor dem Commit der Mutation),
        damit Mutation + Audit atomar committen. ``data`` trägt nur id-Referenzen/Beträge
        (keine PII, security.md §4)."""
        await audit_record(
            self.session,
            actor=self.actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            data=data or {},
        )

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
            await self.session.execute(select(FiscalYear).where(FiscalYear.id == fiscal_year_id))
        ).scalar_one_or_none()
        if fy is None:
            raise NotFoundError(f"fiscal year {fiscal_year_id} not found")
        return fy

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    async def _top_level(self, node: Budget) -> Budget:
        """Top-Level-Budget eines Knotens (erstes Pfad-Segment, ``parent_id IS NULL``)."""
        top_path = node.path_key.split(_SEP, 1)[0]
        top = (
            await self.session.execute(
                select(Budget).where(Budget.path_key == top_path, Budget.parent_id.is_(None))
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
            raise ConflictError(f"budget key {payload.key!r} already exists under this parent")

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
        await self._audit(
            AuditAction.BUDGET_NODE_CREATE,
            target_type="budget",
            target_id=str(node.id),
            data={
                "pathKey": node.path_key,
                "gremiumId": str(gremium_id) if gremium_id else None,
            },
        )
        await self.session.commit()
        return _node_out(node)

    async def _sibling_exists(self, parent_id: UUID | None, key: str) -> bool:
        existing = (
            await self.session.execute(
                select(Budget).where(
                    Budget.parent_id.is_(parent_id)
                    if parent_id is None
                    else Budget.parent_id == parent_id,
                    Budget.key == key,
                )
            )
        ).scalar_one_or_none()
        return existing is not None

    async def update_node(self, budget_id: UUID, payload: BudgetNodeUpdate) -> BudgetNodeOut:
        """Name/Aktiv-Status/Stichtag/**Key** ändern (Parent immutabel → Baum-Stabilität).

        Wird der ``key`` geändert, leitet sich der ``path_key`` des Knotens **und aller
        Nachfahren** neu ab (alles referenziert ``budget_id``, nicht den Pfad). Ändert
        sich der HHJ-Stichtag eines Top-Budgets, leiten sich die Start-/End-Daten aller
        bestehenden HHJ neu daraus ab (Jahr bleibt, Datum folgt)."""
        node = await self._get_node(budget_id)
        provided = payload.model_dump(exclude_unset=True)
        new_key = provided.pop("key", None)
        stichtag_changed = (
            "fiscal_start_month" in provided
            and provided["fiscal_start_month"] != node.fiscal_start_month
        ) or (
            "fiscal_start_day" in provided and provided["fiscal_start_day"] != node.fiscal_start_day
        )
        for field, value in provided.items():
            setattr(node, field, value)
        if new_key is not None and new_key != node.key:
            await self._rename_key(node, new_key)
        if stichtag_changed and node.parent_id is None:
            for fy in await self._fiscal_years_of(budget_id):
                fy.start_date, fy.end_date = self._fiscal_year_bounds(
                    fy.year, node.fiscal_start_month, node.fiscal_start_day
                )
        await self._audit(
            AuditAction.BUDGET_NODE_UPDATE,
            target_type="budget",
            target_id=str(node.id),
            data={"fields": sorted(provided), "keyProvided": new_key is not None},
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
            raise ConflictError(f"budget key {new_key!r} already exists under this parent")
        parent_path: str | None = None
        if node.parent_id is not None:
            parent_path = (await self._get_node(node.parent_id)).path_key
        old_path = node.path_key
        new_path = tree_rules.compose_path_key(parent_path, new_key)
        # Nachfahren (Pfad-Präfix) holen, bevor der Knoten umbenannt wird.
        descendants = (
            (
                await self.session.execute(
                    select(Budget).where(Budget.path_key.like(old_path + _SEP + "%"))
                )
            )
            .scalars()
            .all()
        )
        node.key = new_key
        node.path_key = new_path
        for d in descendants:
            d.path_key = new_path + d.path_key[len(old_path) :]

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
                select(BudgetAllocation.id).where(BudgetAllocation.budget_id == budget_id).limit(1)
            )
        ).scalar_one_or_none()
        if alloc is not None:
            raise ConflictError("budget has allocations; remove them first")
        await self._audit(
            AuditAction.BUDGET_NODE_DELETE,
            target_type="budget",
            target_id=str(budget_id),
            data={"pathKey": node.path_key},
        )
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
            )
            .scalars()
            .all()
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

    async def can_view_node(self, budget_id: UUID, member_gremium_ids: set[UUID]) -> bool:
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
            fid: tree_rules.fiscal_year_display(year, month, day) for fid, year, month, day in rows
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

    @staticmethod
    def _fiscal_year_bounds(year: int, start_month: int, start_day: int) -> tuple[date, date]:
        """HHJ-Grenzen ableiten; unmöglicher Stichtag → 422 statt 500 (#sec-audit).

        Die Schemata begrenzen ``fiscalStartDay`` bereits auf ``1..28`` — diese
        Hülle ist die Defensive für Altbestand / direkte Service-Aufrufe."""
        try:
            return tree_rules.fiscal_year_bounds(year, start_month, start_day)
        except ValueError as exc:
            raise ValidationProblem(
                "Invalid fiscal year start date.",
                errors=[{"field": "fiscalStartDay", "msg": str(exc)}],
            ) from exc

    async def create_fiscal_year(self, budget_id: UUID, payload: FiscalYearCreate) -> FiscalYearOut:
        """HHJ (Jahr) anlegen — Start/Ende aus Budget-Stichtag; eindeutig pro Top-Budget."""
        top = await self._require_top_level(budget_id)
        start, end = self._fiscal_year_bounds(
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
            fy.start_date, fy.end_date = self._fiscal_year_bounds(
                new_year, top.fiscal_start_month, top.fiscal_start_day
            )
        if "active" in provided:
            fy.active = provided["active"]
        await self.session.commit()
        return _fy_out(fy, top.fiscal_start_month, top.fiscal_start_day)

    # ------------------------------------------------------------- allocation
    async def _allocation(self, budget_id: UUID, fiscal_year_id: UUID) -> BudgetAllocation | None:
        return (
            await self.session.execute(
                select(BudgetAllocation).where(
                    BudgetAllocation.budget_id == budget_id,
                    BudgetAllocation.fiscal_year_id == fiscal_year_id,
                )
            )
        ).scalar_one_or_none()

    async def _lock_budget(self, budget_id: UUID) -> None:
        """Budget-Zeile pessimistisch sperren (``SELECT … FOR UPDATE``) — race-frei.

        Serialisiert konkurrierende Geschwister-Zuteilungen: alle sperren dieselbe
        Parent-Zeile, sodass Lese-Summe + Validierung + Schreiben atomar bleiben und
        keine doppelte Über-Allokation durchschlüpfen kann (#sec-audit)."""
        await self.session.execute(
            select(Budget.id).where(Budget.id == budget_id).with_for_update()
        )

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

        # Pessimistische Sperre VOR Lesen+Validieren+Schreiben (#sec-audit, race-frei):
        # Die eigene Budget-Zeile sperrt den Abwärts-Constraint (eigene Kinder), die
        # Parent-Zeile serialisiert alle konkurrierenden Geschwister-Zuteilungen — beide
        # lesen dann dieselbe, bereits gesperrte Geschwister-Summe und können nicht
        # gemeinsam überbuchen.
        await self._lock_budget(node.id)
        if node.parent_id is not None:
            await self._lock_budget(node.parent_id)

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
        await self._audit(
            AuditAction.BUDGET_ALLOCATION_SET,
            target_type="budget_allocation",
            target_id=str(budget_id),
            data={"fiscalYearId": str(fiscal_year_id), "allocated": str(payload.allocated)},
        )
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
            await self._audit(
                AuditAction.BUDGET_ASSIGN,
                target_type="application",
                target_id=str(app.id),
                data={"budgetId": None, "fiscalYearId": None},
            )
            await self.session.commit()
            return AssignBudgetOut(applicationId=app.id, budgetId=None, fiscalYearId=None)

        node = await self._get_node(payload.budget_id)
        top = await self._top_level(node)
        active_ids = [f.id for f in await self._fiscal_years_of(top.id) if f.active]
        fy_id = tree_rules.pick_fiscal_year(active_ids)
        app.budget_id = node.id
        app.fiscal_year_id = fy_id
        await self._audit(
            AuditAction.BUDGET_ASSIGN,
            target_type="application",
            target_id=str(app.id),
            data={"budgetId": str(node.id), "fiscalYearId": str(fy_id) if fy_id else None},
        )
        await self.session.commit()
        return AssignBudgetOut(applicationId=app.id, budgetId=node.id, fiscalYearId=fy_id)

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
        await self._audit(
            AuditAction.BUDGET_MOVE_FISCAL_YEAR,
            target_type="application",
            target_id=str(app.id),
            data={"budgetId": str(app.budget_id), "fiscalYearId": str(fy.id)},
        )
        await self.session.commit()
        return AssignBudgetOut(applicationId=app.id, budgetId=app.budget_id, fiscalYearId=fy.id)

    # --------------------------------------------------------------- expenses
    async def _resolve_expense_fiscal_year(self, node: Budget, fiscal_year_id: UUID | None) -> UUID:
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

    async def _actor_names(self, subs: set[str]) -> dict[str, str]:
        """Buchungs-Actor (principal.sub) → Klarname (display_name/email/sub).

        Spiegelt ``ApplicationsService._author_names`` (#no-uuids-in-ui): die UUID
        des Buchenden darf nie im UI landen. Legacy-Actor, die schon ein Name sind,
        finden keinen Principal-Treffer und fehlen im Dict (FE fällt auf ``actor``).
        """
        from app.modules.auth.models import Principal as PrincipalRow

        wanted = {s for s in subs if s}
        if not wanted:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.sub, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.sub.in_(wanted)
                )
            )
        ).all()
        return {sub: (dn or em or sub) for sub, dn, em in rows}

    @staticmethod
    def _expense_out(
        e: BudgetExpense,
        path_key: str | None,
        app_title: str | None = None,
        account_name: str | None = None,
        invoice_number: str | None = None,
        actor_name: str | None = None,
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
            actorName=actor_name,
            invoiceDate=e.invoice_date,
            paymentDate=e.payment_date,
            correspondent=e.correspondent,
            note=e.note,
            referenceNumber=e.reference_number,
            paymentMethod=e.payment_method,  # type: ignore[arg-type]
            category=e.category,
            invoiceId=e.invoice_id,
            invoiceNumber=invoice_number,
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
            invoice_date=payload.invoice_date,
            payment_date=payload.payment_date,
            correspondent=payload.correspondent,
            note=payload.note,
            reference_number=payload.reference_number,
            payment_method=payload.payment_method,
            category=payload.category,
            invoice_id=payload.invoice_id,
        )
        self.session.add(expense)
        await self._audit(
            AuditAction.BUDGET_EXPENSE_CREATE,
            target_type="budget_expense",
            target_id=str(expense.id),
            data={
                "budgetId": str(node.id),
                "fiscalYearId": str(fy_id),
                "kind": payload.kind,
                "amount": str(payload.amount),
                "applicationId": (str(payload.application_id) if payload.application_id else None),
            },
        )
        await self.session.commit()
        names = await self._actor_names({expense.actor} if expense.actor else set())
        return self._expense_out(
            expense,
            node.path_key,
            app_title,
            account_name,
            actor_name=names.get(expense.actor or ""),
        )

    async def _validate_account(self, account_id: UUID | None) -> str | None:
        """Konto prüfen (falls angegeben) → Name; sonst ``None``."""
        if account_id is None:
            return None
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        return acc.name

    async def update_expense(self, expense_id: UUID, payload: ExpenseUpdate) -> ExpenseOut:
        """Buchung ändern (#25): Betrag, Beschreibung, Bankkonto und Zusatz-Metadaten
        (Daten, Empfänger/Zahler, Anmerkungen, Belegnummer, Zahlungsmethode, Kategorie).
        HHJ/Kostenstelle/Antragsbindung bleiben fix. Nur gesetzte Felder werden
        geschrieben; explizites ``null`` leert ein optionales Feld."""
        expense = await self.session.get(BudgetExpense, expense_id)
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        fields = payload.model_fields_set
        if "amount" in fields and payload.amount is not None:
            expense.amount = payload.amount
        if "description" in fields and payload.description is not None:
            expense.description = payload.description
        if "account_id" in fields:
            await self._validate_account(payload.account_id)  # 404, falls unbekannt
            expense.account_id = payload.account_id
        if "invoice_date" in fields:
            expense.invoice_date = payload.invoice_date
        if "payment_date" in fields:
            expense.payment_date = payload.payment_date
        if "correspondent" in fields:
            expense.correspondent = payload.correspondent
        if "note" in fields:
            expense.note = payload.note
        if "reference_number" in fields:
            expense.reference_number = payload.reference_number
        if "payment_method" in fields:
            expense.payment_method = payload.payment_method
        if "category" in fields:
            expense.category = payload.category
        if "invoice_id" in fields:
            expense.invoice_id = payload.invoice_id
        await self._audit(
            AuditAction.BUDGET_EXPENSE_UPDATE,
            target_type="budget_expense",
            target_id=str(expense.id),
            data={"fields": sorted(fields), "amount": str(expense.amount)},
        )
        await self.session.commit()
        node = await self._get_node(expense.budget_id)
        app_title: str | None = None
        if expense.application_id is not None:
            app = await self.session.get(Application, expense.application_id)
            app_title = _title_of(app.data) if app is not None else None
        # Defensiv (#race): ein paralleles ``delete_account`` (FK SET NULL) kann die
        # Konto-Zeile zwischen Buchung und Re-Read entfernen → ``get`` liefert None.
        acc = (
            await self.session.get(Account, expense.account_id)
            if expense.account_id is not None
            else None
        )
        acc_name = acc.name if acc is not None else None
        names = await self._actor_names({expense.actor} if expense.actor else set())
        return self._expense_out(
            expense, node.path_key, app_title, acc_name, actor_name=names.get(expense.actor or "")
        )

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
        # Fuzzy-Suche (#3): Trigram-Ranking über die Freitext-Felder der Buchung +
        # mitgejointe Texte (Antrag/Konto/Rechnung). ``rank_expr`` ordnet die Treffer;
        # ``where`` hängt an den GETEILTEN ``filters`` (Zähl- UND Zeilen-Query identisch).
        rank_expr = None
        if q and q.strip():
            where, rank_expr = trigram_rank(
                q,
                [
                    BudgetExpense.description,
                    BudgetExpense.correspondent,
                    BudgetExpense.reference_number,
                    BudgetExpense.category,
                    BudgetExpense.note,
                    Invoice.number,
                    Invoice.supplier,
                    Account.name,
                    func.cast(Application.data, _Text),
                ],
                dialect=dialect_of(self.session),
            )
            filters.append(where)
        if amount_min is not None:
            filters.append(BudgetExpense.amount >= amount_min)
        if amount_max is not None:
            filters.append(BudgetExpense.amount <= amount_max)
        if created_from:
            filters.append(func.date(BudgetExpense.created_at) >= created_from)
        if created_to:
            filters.append(func.date(BudgetExpense.created_at) <= created_to)

        # Sortier-Spalte (whitelist) + Richtung; Default: neueste zuerst.
        sort_map = {
            "amount": BudgetExpense.amount,
            "invoiceDate": BudgetExpense.invoice_date,
            "paymentDate": BudgetExpense.payment_date,
        }
        sort_col = sort_map.get(sort or "", BudgetExpense.created_at)
        direction = sort_col.asc() if order == "asc" else sort_col.desc()
        # Nullable Datums-Spalten: leere Werte unabhängig von der Richtung ans Ende.
        ordering = direction.nulls_last() if sort in ("invoiceDate", "paymentDate") else direction

        # Die Suche referenziert mitgejointe Texte (Antrag/Konto/Rechnung) → die
        # Zähl-Query muss dieselben Joins tragen wie die Zeilen-Query, sonst löst das
        # ``where`` über fremde Tabellen nicht auf (bzw. cross-joint). Ohne ``q``
        # bleibt die Zähl-Query schlank (kein Join).
        count_stmt = select(func.count()).select_from(BudgetExpense)
        if rank_expr is not None:
            count_stmt = (
                count_stmt.outerjoin(Application, Application.id == BudgetExpense.application_id)
                .outerjoin(Account, Account.id == BudgetExpense.account_id)
                .outerjoin(Invoice, Invoice.id == BudgetExpense.invoice_id)
            )
        total = await self.session.scalar(count_stmt.where(*filters))
        # Suche aktiv ⇒ relevanteste zuerst (Rang), danach die bisherige Sortierung
        # als deterministischer Tiebreak; ohne Suche unverändert.
        order_by = (
            (rank_expr.desc(), ordering, BudgetExpense.created_at.desc())
            if rank_expr is not None
            else (ordering, BudgetExpense.created_at.desc())
        )
        rows = (
            await self.session.execute(
                select(
                    BudgetExpense,
                    Budget.path_key,
                    Application.data,
                    Account.name,
                    Invoice.number,
                )
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                .outerjoin(Application, Application.id == BudgetExpense.application_id)
                .outerjoin(Account, Account.id == BudgetExpense.account_id)
                .outerjoin(Invoice, Invoice.id == BudgetExpense.invoice_id)
                .where(*filters)
                .order_by(*order_by)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        # Buchenden-UUIDs (#no-uuids-in-ui) gesammelt → Klarnamen in einem Query.
        names = await self._actor_names({row[0].actor for row in rows if row[0].actor})
        items = [
            self._expense_out(
                e,
                path_key,
                _title_of(data) if data else None,
                acc_name,
                inv_number,
                actor_name=names.get(e.actor or ""),
            )
            for (e, path_key, data, acc_name, inv_number) in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

    async def delete_expense(self, expense_id: UUID) -> None:
        """Ausgabe löschen (#25). Teil eines Übertrags → beide Buchungen löschen."""
        expense = (
            await self.session.execute(select(BudgetExpense).where(BudgetExpense.id == expense_id))
        ).scalar_one_or_none()
        if expense is None:
            raise NotFoundError(f"budget expense {expense_id} not found")
        await self._audit(
            AuditAction.BUDGET_EXPENSE_DELETE,
            target_type="budget_expense",
            target_id=str(expense_id),
            data={
                "budgetId": str(expense.budget_id),
                "kind": expense.kind,
                "amount": str(expense.amount),
                "priorActor": expense.actor,
                "transferId": str(expense.transfer_id) if expense.transfer_id else None,
            },
        )
        if expense.transfer_id is not None:
            pair = (
                (
                    await self.session.execute(
                        select(BudgetExpense).where(
                            BudgetExpense.transfer_id == expense.transfer_id
                        )
                    )
                )
                .scalars()
                .all()
            )
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
        rows = (await self.session.scalars(select(Account).order_by(Account.name))).all()
        return [self._account_out(a) for a in rows]

    async def list_account_options(self) -> list[AccountOption]:
        """Aktive Konten als id+Name (ohne IBAN) für Buchungs-Dropdowns (#5-2/#2)."""
        rows = (
            await self.session.scalars(
                select(Account).where(Account.active.is_(True)).order_by(Account.name)
            )
        ).all()
        return [AccountOption(id=a.id, name=a.name) for a in rows]

    async def create_account(self, payload: AccountCreate) -> AccountOut:
        acc = Account(id=uuid.uuid4(), name=payload.name, iban=payload.iban, active=payload.active)
        self.session.add(acc)
        await self.session.commit()
        return self._account_out(acc)

    async def update_account(self, account_id: UUID, payload: AccountUpdate) -> AccountOut:
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

    # --------------------------------------------------------------- invoices
    @staticmethod
    def _invoice_out(inv: Invoice) -> InvoiceOut:
        return InvoiceOut(
            id=inv.id,
            number=inv.number,
            issueDate=inv.issue_date,
            dueDate=inv.due_date,
            supplier=inv.supplier,
            netAmount=inv.net_amount,
            taxAmount=inv.tax_amount,
            grossAmount=inv.gross_amount,
            currency=inv.currency,
            note=inv.note,
            status=inv.status,  # type: ignore[arg-type]
            fileName=inv.file_name,
            hasFile=inv.file_object_key is not None,
            actor=inv.actor,
            createdAt=inv.created_at,
        )

    async def list_invoices(self) -> list[InvoiceOut]:
        """(Kompat) Alle Rechnungen (neuestes Rechnungsdatum zuerst) — für das
        Buchungs-Verknüpfungs-Dropdown (#invoices), das die volle Liste braucht."""
        page = await self.list_invoices_paged(limit=10_000, offset=0)
        return page.items

    async def list_invoices_paged(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        gross_min: Decimal | None = None,
        gross_max: Decimal | None = None,
        issue_from: str | None = None,
        issue_to: str | None = None,
        due_from: str | None = None,
        due_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[InvoiceOut]:
        """Rechnungen gefiltert + fuzzy-gesucht + offset-paginiert (#invoices).

        Spiegelt :meth:`list_expenses_paged`: die Such-/Filter-Prädikate hängen an
        einer GETEILTEN ``filters``-Liste, die identisch in die Zähl- **und** die
        Zeilen-Query geht (kein ``total``/Treffer-Drift beim Infinite-Scroll). Mit
        Suchbegriff ``q`` ordnet der Trigram-Rang die Treffer nach Relevanz vor das
        bisherige »neuestes Rechnungsdatum zuerst«.
        """
        filters = []
        # Fuzzy-Suche (#3/#4): Trigram-Ranking über Nummer/Lieferant/Notiz (GIN-Indizes
        # aus Migration 0027). Auf Nicht-Postgres greift der ILIKE-Substring-Fallback.
        rank_expr = None
        if q and q.strip():
            where, rank_expr = trigram_rank(
                q,
                [Invoice.number, Invoice.supplier, Invoice.note],
                dialect=dialect_of(self.session),
            )
            filters.append(where)
        if status is not None:
            filters.append(Invoice.status == status)
        if gross_min is not None:
            filters.append(Invoice.gross_amount >= gross_min)
        if gross_max is not None:
            filters.append(Invoice.gross_amount <= gross_max)
        # Nullable Datums-Spalten: eine Rechnung ohne Datum fällt aus jedem gesetzten
        # Bereich (wie die bisherige Client-Logik ``inDateRange``). ``func.date`` parst
        # den ISO-String aus dem FE-Datepicker zu einem echten Datum — Postgres würde
        # sonst ``date >= varchar`` ablehnen; auf SQLite ein No-Op (ISO bleibt ISO).
        if issue_from:
            filters.append(Invoice.issue_date >= func.date(issue_from))
        if issue_to:
            filters.append(Invoice.issue_date <= func.date(issue_to))
        if due_from:
            filters.append(Invoice.due_date >= func.date(due_from))
        if due_to:
            filters.append(Invoice.due_date <= func.date(due_to))

        total = await self.session.scalar(
            select(func.count()).select_from(Invoice).where(*filters)
        )
        ordering = Invoice.issue_date.desc().nulls_last()
        order_by = (rank_expr.desc(), ordering) if rank_expr is not None else (ordering,)
        rows = (
            await self.session.scalars(
                select(Invoice).where(*filters).order_by(*order_by).limit(limit).offset(offset)
            )
        ).all()
        return Page(
            items=[self._invoice_out(i) for i in rows],
            total=total or 0,
            limit=limit,
            offset=offset,
        )

    async def get_invoice(self, invoice_id: UUID) -> InvoiceOut:
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        return self._invoice_out(inv)

    async def create_invoice(self, payload: InvoiceCreate, *, actor: str) -> InvoiceOut:
        inv = Invoice(
            number=payload.number,
            issue_date=payload.issue_date,
            due_date=payload.due_date,
            supplier=payload.supplier,
            net_amount=payload.net_amount,
            tax_amount=payload.tax_amount,
            gross_amount=payload.gross_amount,
            note=payload.note,
            status=payload.status,
            actor=actor,
        )
        if payload.file_token is not None:
            # Beleg aus dem ZUGFeRD-Import übernehmen (#15) — der Token ist der
            # bereits gespeicherte MinIO-Key (Prefix-validiert gegen Fremdobjekte).
            inv.file_object_key = _validate_invoice_file_token(payload.file_token)
            inv.file_name = payload.file_name
            inv.file_mime = payload.file_mime
        self.session.add(inv)
        await self.session.flush()  # id für den Audit-Eintrag erzeugen
        await self._audit(
            AuditAction.BUDGET_INVOICE_CREATE,
            target_type="invoice",
            target_id=str(inv.id),
            data={"number": inv.number, "gross": str(inv.gross_amount)},
        )
        await self.session.commit()
        return self._invoice_out(inv)

    # ------------------------------------------------------ ZUGFeRD-Import (#15)
    async def _validate_scan_store(
        self, data: bytes, *, filename: str | None
    ) -> tuple[str, str, str]:
        """PDF prüfen (Größe/MIME/AV-Scan) und ablegen → (token, safe_name, mime).

        Gemeinsamer Pfad für ZUGFeRD-Parse und manuellen Beleg-Upload (#invoices).
        """
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"Invoice exceeds {max_bytes} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        try:
            mime = validate_upload(filename, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if mime != "application/pdf":
            raise UnsupportedMediaTypeError("Invoice import expects a PDF.")

        await self._scan_or_raise(data)
        safe_name = sanitize_filename(filename)
        storage_key = await self._store_invoice_file(data, mime, safe_name)
        return storage_key, safe_name, mime

    async def store_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceFileResult:
        """Beleg-PDF prüfen + ablegen (ohne ZUGFeRD-Parse) — für manuelle Belege.

        Erlaubt das Anhängen eines Originals an **nicht**-ZUGFeRD-Rechnungen
        (#invoices): liefert denselben ``fileToken``, den ``POST /invoices`` erwartet.
        """
        storage_key, safe_name, mime = await self._validate_scan_store(data, filename=filename)
        return InvoiceFileResult(fileToken=storage_key, fileName=safe_name, fileMime=mime)

    async def parse_invoice_file(self, data: bytes, *, filename: str | None) -> InvoiceParseResult:
        """PDF prüfen (MIME + AV-Scan), ZUGFeRD parsen, Original ablegen.

        Reihenfolge bewusst: scannen → parsen → erst danach speichern, damit ein
        Nicht-ZUGFeRD-PDF (häufigster Fall) **kein** verwaistes Objekt hinterlässt.
        """
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise PayloadTooLargeError(f"Invoice exceeds {max_bytes} bytes.")
        if not data:
            raise UnsupportedMediaTypeError("Empty file.")
        try:
            mime = validate_upload(filename, data)
        except MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if mime != "application/pdf":
            raise UnsupportedMediaTypeError("Invoice import expects a PDF.")

        await self._scan_or_raise(data)
        # Parsing ist synchron/CPU-gebunden → Threadpool (keine Loop-Blockade).
        parsed = await asyncio.to_thread(parse_zugferd_pdf, data)

        safe_name = sanitize_filename(filename)
        storage_key = await self._store_invoice_file(data, mime, safe_name)
        return InvoiceParseResult(
            number=parsed.number,
            issueDate=parsed.issue_date,
            dueDate=parsed.due_date,
            supplier=parsed.supplier,
            netAmount=parsed.net_amount,
            taxAmount=parsed.tax_amount,
            grossAmount=parsed.gross_amount,
            currency=parsed.currency,
            fileToken=storage_key,
            fileName=safe_name,
            fileMime=mime,
            duplicate=await self._invoice_number_exists(parsed.number),
        )

    async def _invoice_number_exists(self, number: str | None) -> bool:
        """Existiert bereits eine Rechnung mit dieser Nummer? (Dubletten-Warnung)."""
        if not number:
            return False
        existing = await self.session.scalars(
            select(Invoice.id).where(Invoice.number == number).limit(1)
        )
        return existing.first() is not None

    async def invoice_file_bytes(self, invoice_id: UUID) -> tuple[bytes, str, str]:
        """Original-Beleg serverseitig laden → (data, mime, filename).

        Bewusst **kein** presigned-URL: MinIO liegt nur im internen Docker-Netz,
        eine S3v4-signierte URL bindet den internen Host und ist vom Browser
        unerreichbar (#invoices) — wie beim Protokoll-PDF streamen wir über die API.
        """
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        if inv.file_object_key is None:
            raise NotFoundError("invoice has no stored file")
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        try:
            data = await self.storage.get(inv.file_object_key)
        except StorageError as exc:
            raise ServiceUnavailableError("Could not read invoice file.") from exc
        return data, inv.file_mime or "application/pdf", inv.file_name or "beleg.pdf"

    async def _scan_or_raise(self, data: bytes) -> None:
        """Synchroner AV-Scan. Ohne ClamAV (DEV/Contract-CI) übersprungen — in
        ``production`` aber **fail-closed**: kein ungescanntes Beleg-PDF ablegen,
        wenn der Scanner fehlt (konsistent zur Files-Quarantäne, #sec-audit)."""
        scanner = build_scanner(self.settings)
        if scanner is None:
            if self.settings.environment == "production":
                raise ServiceUnavailableError("Virus scan unavailable.")
            return
        try:
            verdict = await scanner.scan(data)
        except ScannerError as exc:
            raise ServiceUnavailableError("Virus scan unavailable.") from exc
        if not verdict.clean:
            raise UnsupportedMediaTypeError(
                f"File rejected by virus scan: {verdict.signature or 'unknown'}"
            )

    async def _store_invoice_file(self, data: bytes, mime: str, safe_name: str) -> str:
        if self.storage is None:
            raise ServiceUnavailableError("Object storage unavailable.")
        storage_key = f"invoices/{uuid.uuid4().hex}/{safe_name}"
        try:
            await self.storage.put(storage_key, data, mime)
        except StorageError as exc:
            raise ServiceUnavailableError("Object storage write failed.") from exc
        return storage_key

    async def update_invoice(self, invoice_id: UUID, payload: InvoiceUpdate) -> InvoiceOut:
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        fields = payload.model_fields_set
        if "number" in fields:
            inv.number = payload.number
        if "issue_date" in fields:
            inv.issue_date = payload.issue_date
        if "due_date" in fields:
            inv.due_date = payload.due_date
        if "supplier" in fields:
            inv.supplier = payload.supplier
        if "net_amount" in fields:
            inv.net_amount = payload.net_amount
        if "tax_amount" in fields:
            inv.tax_amount = payload.tax_amount
        if "gross_amount" in fields and payload.gross_amount is not None:
            inv.gross_amount = payload.gross_amount
        if "note" in fields:
            inv.note = payload.note
        if "status" in fields and payload.status is not None:
            inv.status = payload.status
        await self._audit(
            AuditAction.BUDGET_INVOICE_UPDATE,
            target_type="invoice",
            target_id=str(invoice_id),
            data={"fields": sorted(fields)},
        )
        await self.session.commit()
        return self._invoice_out(inv)

    async def delete_invoice(self, invoice_id: UUID) -> None:
        inv = await self.session.get(Invoice, invoice_id)
        if inv is None:
            raise NotFoundError(f"invoice {invoice_id} not found")
        # Buchungen behalten invoice_id=NULL (FK SET NULL).
        storage_key = inv.file_object_key
        await self._audit(
            AuditAction.BUDGET_INVOICE_DELETE,
            target_type="invoice",
            target_id=str(invoice_id),
            data={"number": inv.number, "gross": str(inv.gross_amount)},
        )
        await self.session.delete(inv)
        await self.session.commit()
        if storage_key is not None and self.storage is not None:
            # Original-Beleg best-effort entfernen (fehlt es schon, gilt das Löschen).
            try:
                await self.storage.remove(storage_key)
            except StorageError:
                logger.warning("could not remove file for deleted invoice %s", invoice_id)

    # --------------------------------------------------------------- transfer
    async def create_transfer(self, payload: TransferCreate, *, actor: str) -> TransferOut:
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
            id=uuid.uuid4(),
            budget_id=src.id,
            fiscal_year_id=fy_src,
            transfer_id=transfer_id,
            kind="expense",
            amount=payload.amount,
            currency=src.currency,
            description=payload.description,
            actor=actor,
        )
        in_row = BudgetExpense(
            id=uuid.uuid4(),
            budget_id=dst.id,
            fiscal_year_id=fy_dst,
            transfer_id=transfer_id,
            kind="income",
            amount=payload.amount,
            currency=dst.currency,
            description=payload.description,
            actor=actor,
        )
        self.session.add_all([out_row, in_row])
        await self._audit(
            AuditAction.BUDGET_TRANSFER_CREATE,
            target_type="budget_transfer",
            target_id=str(transfer_id),
            data={
                "fromBudgetId": str(src.id),
                "toBudgetId": str(dst.id),
                "fiscalYearId": str(fy_src),
                "amount": str(payload.amount),
            },
        )
        await self.session.commit()
        return TransferOut(transferId=transfer_id, expenseId=out_row.id, incomeId=in_row.id)

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
        nodes = list((await self.session.execute(select(Budget))).scalars().all())
        # Natürliche Reihenfolge (VSM-10 nach VSM-9 statt lexikografisch); Eltern vor
        # Kindern bleibt erhalten → build_forest erbt die Geschwister-Reihenfolge.
        nodes.sort(key=lambda b: _natural_path_key(b.path_key))
        allocs = (await self.session.execute(select(BudgetAllocation))).scalars().all()
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
                spent_per_app[app_id] = spent_per_app.get(app_id, _ZERO) + (amount or _ZERO)

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
            return any(path == fp or path.startswith(fp + _SEP) for fp in flagged_paths)

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
                n.id,
                n.parent_id,
                n.gremium_id,
                n.key,
                n.path_key,
                n.name,
                n.currency,
                n.active,
                n.color,
                list(n.accepted_state_keys or []),
                list(n.denied_state_keys or []),
                n.fiscal_start_month,
                n.fiscal_start_day,
                n.fully_bound,
                bool(n.hidden_in_budget),
                n.view_gremium_id,
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
