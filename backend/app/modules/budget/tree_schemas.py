"""API-Schemata des Budget-Baums (CR #76/#78, api.md »budget«).

camelCase-Aliase via :class:`_CamelModel` (``by_alias``); Geld als ``Decimal``
(numeric(12,2)); Datum als ``date``. ``pathKey`` ist server-gepflegt → im Request
nicht akzeptiert, nur in Out-DTOs.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.modules.budget.schemas import _CamelModel


# --------------------------------------------------------------------- nodes
class BudgetNodeCreate(_CamelModel):
    """Kostenstelle anlegen. ``parentId=null`` → Top-Level (``gremiumId`` Pflicht)."""

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parent_id: UUID | None = Field(default=None, alias="parentId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    active: bool = True
    color: str | None = None


class BudgetNodeUpdate(_CamelModel):
    """Kostenstelle teil-aktualisieren (Key/Parent unveränderlich → Pfad-Stabilität).

    ``None`` = unverändert. ``color=""`` löscht die Farbe. ``acceptedStateKeys``/
    ``deniedStateKeys`` nur am Top-Level sinnvoll (Beantragt/Gebunden-Klassifikation)."""

    name: str | None = Field(default=None, min_length=1)
    active: bool | None = None
    color: str | None = None
    accepted_state_keys: list[str] | None = Field(default=None, alias="acceptedStateKeys")
    denied_state_keys: list[str] | None = Field(default=None, alias="deniedStateKeys")


class BudgetNodeOut(_CamelModel):
    """Stammdaten eines Knotens."""

    id: UUID
    parent_id: UUID | None = Field(alias="parentId")
    gremium_id: UUID | None = Field(alias="gremiumId")
    key: str
    path_key: str = Field(alias="pathKey")
    name: str
    currency: str
    active: bool
    color: str | None = None
    accepted_state_keys: list[str] = Field(default_factory=list, alias="acceptedStateKeys")
    denied_state_keys: list[str] = Field(default_factory=list, alias="deniedStateKeys")


class AllocationView(_CamelModel):
    """Verfügbar/gebunden/beantragt eines Knotens in **einem** HHJ (R7.1b/c)."""

    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal
    committed: Decimal
    requested: Decimal = Decimal("0")
    available: Decimal


class BudgetTreeNodeOut(_CamelModel):
    """Baumknoten + Summen je HHJ + Kinder (rekursiv) — ``GET /budgets``."""

    id: UUID
    parent_id: UUID | None = Field(alias="parentId")
    gremium_id: UUID | None = Field(alias="gremiumId")
    key: str
    path_key: str = Field(alias="pathKey")
    name: str
    currency: str
    active: bool
    color: str | None = None
    accepted_state_keys: list[str] = Field(default_factory=list, alias="acceptedStateKeys")
    denied_state_keys: list[str] = Field(default_factory=list, alias="deniedStateKeys")
    by_fiscal_year: list[AllocationView] = Field(
        default_factory=list, alias="byFiscalYear"
    )
    children: list[BudgetTreeNodeOut] = Field(default_factory=list)


# ---------------------------------------------------------------- fiscal years
class FiscalYearCreate(_CamelModel):
    """Haushaltsjahr anlegen (Start ≠ zwingend 01.01.; disjunkt pro Top-Budget)."""

    label: str = Field(min_length=1)
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    active: bool = True


class FiscalYearUpdate(_CamelModel):
    """Haushaltsjahr ändern (Disjunktheit erneut geprüft)."""

    label: str | None = Field(default=None, min_length=1)
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    active: bool | None = None


class FiscalYearOut(_CamelModel):
    """Haushaltsjahr-Stammdaten."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    label: str
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    active: bool


# ----------------------------------------------------------------- allocation
class AllocationSet(_CamelModel):
    """Top-Down-Zuteilung setzen (``PUT …/allocations/{fiscalYearId}``)."""

    allocated: Decimal = Field(ge=0, allow_inf_nan=False)


class AllocationOut(_CamelModel):
    """Ergebnis einer Zuteilung."""

    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal


# ------------------------------------------------------------------- assign
class AssignBudgetRequest(_CamelModel):
    """Antrag einer Kostenstelle zuordnen; setzt zugleich HHJ (R7.1e).

    ``budgetId=null`` löst die Zuordnung (auch ``fiscalYearId`` → null).
    """

    budget_id: UUID | None = Field(default=None, alias="budgetId")


class MoveFiscalYearRequest(_CamelModel):
    """Antrag in anderes HHJ verschieben (``fiscalYearId`` des Top-Budgets)."""

    fiscal_year_id: UUID = Field(alias="fiscalYearId")


class AssignBudgetOut(_CamelModel):
    """Ergebnis einer Kostenstellen-/HHJ-Zuordnung."""

    application_id: UUID = Field(alias="applicationId")
    budget_id: UUID | None = Field(alias="budgetId")
    fiscal_year_id: UUID | None = Field(alias="fiscalYearId")


class BudgetApplicationOut(_CamelModel):
    """Antrag in einer Kostenstelle (+ Unterbaum) — für die Budget-Statistik-Drilldown-
    Liste (#17). Geld als ``Decimal``; ``stage`` aus dem ``budget_entry`` (oder None)."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    path_key: str | None = Field(default=None, alias="pathKey")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    amount: Decimal | None = None
    currency: str | None = None
    stage: str | None = None
    state_id: UUID | None = Field(default=None, alias="stateId")
    created_at: datetime = Field(alias="createdAt")


# ------------------------------------------------------------------- expense
class ExpenseCreate(_CamelModel):
    """Eigenständige Ausgabe buchen (#25) — ohne Antrag, gegen Kostenstelle + HHJ.

    ``fiscalYearId`` ist optional: fehlt es, wird das **eine** aktive HHJ des
    Top-Budgets gewählt (mehrdeutig/keins → 422).
    """

    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    description: str = Field(min_length=1)
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")


class ExpenseOut(_CamelModel):
    """Gebuchte Ausgabe (Stammdaten)."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    path_key: str | None = Field(default=None, alias="pathKey")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    amount: Decimal
    currency: str
    description: str
    actor: str | None = None
    created_at: datetime = Field(alias="createdAt")


BudgetTreeNodeOut.model_rebuild()

__all__ = [
    "BudgetApplicationOut",
    "AllocationOut",
    "AllocationSet",
    "AllocationView",
    "AssignBudgetOut",
    "AssignBudgetRequest",
    "BudgetNodeCreate",
    "BudgetNodeOut",
    "BudgetNodeUpdate",
    "BudgetTreeNodeOut",
    "ExpenseCreate",
    "ExpenseOut",
    "FiscalYearCreate",
    "FiscalYearOut",
    "FiscalYearUpdate",
    "MoveFiscalYearRequest",
]
