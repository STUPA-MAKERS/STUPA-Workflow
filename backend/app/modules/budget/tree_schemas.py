"""API-Schemata des Budget-Baums (CR #76/#78, api.md »budget«).

camelCase-Aliase via :class:`_CamelModel` (``by_alias``); Geld als ``Decimal``
(numeric(12,2)); Datum als ``date``. ``pathKey`` ist server-gepflegt → im Request
nicht akzeptiert, nur in Out-DTOs.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

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
    """Budget-Sicht eines Knotens in **einem** HHJ (R7.1b/c, #25).

    ``committed`` = ``bound + expended`` (Gesamt-Verbrauch, abwärtskompatibel).
    ``available = allocated − bound − expended + income``.
    """

    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal
    # Gebunden: angenommene Anträge, anteilig um gebundene Ausgaben gemindert.
    bound: Decimal = Decimal("0")
    # Ausgegeben: tatsächliche Ausgaben (kind='expense').
    expended: Decimal = Decimal("0")
    # Einnahmen (kind='income') — erhöhen das verfügbare Budget.
    income: Decimal = Decimal("0")
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
ExpenseKind = Literal["expense", "income"]


class ExpenseCreate(_CamelModel):
    """Ausgabe/Einnahme buchen (#25) — gegen Kostenstelle + HHJ, optional an Antrag.

    * ``budgetId`` Pflicht für eigenständige Buchungen; bei gebundenen (``applicationId``
      gesetzt) wird die Kostenstelle **vom Antrag geerbt** und ``budgetId``/``fiscalYearId``
      ignoriert.
    * ``applicationId`` bindet die Buchung an einen Antrag (ersetzt dessen Bindung
      anteilig). Nur für ``kind='expense'`` erlaubt.
    * ``fiscalYearId`` optional bei eigenständigen Ausgaben: fehlt es, wird das **eine**
      aktive HHJ des Top-Budgets gewählt (mehrdeutig/keins → 422).
    """

    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    description: str = Field(min_length=1)
    kind: ExpenseKind = "expense"
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    application_id: UUID | None = Field(default=None, alias="applicationId")

    @model_validator(mode="after")
    def _income_not_linkable(self) -> ExpenseCreate:
        if self.kind == "income" and self.application_id is not None:
            raise ValueError("income cannot be linked to an application")
        return self


class ExpenseUpdate(_CamelModel):
    """Gebuchte Ausgabe/Einnahme ändern (Betrag/Beschreibung). Kostenstelle, HHJ und
    Antragsbindung bleiben fix (Pfad-/Buchungsstabilität)."""

    amount: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    description: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _at_least_one(self) -> ExpenseUpdate:
        if self.amount is None and self.description is None:
            raise ValueError("at least one of 'amount' or 'description' required")
        return self


class ExpenseOut(_CamelModel):
    """Gebuchte Ausgabe/Einnahme (Stammdaten)."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    path_key: str | None = Field(default=None, alias="pathKey")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    kind: ExpenseKind = "expense"
    amount: Decimal
    currency: str
    description: str
    application_id: UUID | None = Field(default=None, alias="applicationId")
    application_title: str | None = Field(default=None, alias="applicationTitle")
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
    "ExpenseKind",
    "ExpenseOut",
    "ExpenseUpdate",
    "FiscalYearCreate",
    "FiscalYearOut",
    "FiscalYearUpdate",
    "MoveFiscalYearRequest",
]
