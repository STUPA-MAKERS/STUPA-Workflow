"""API-Schemata des Budget-Moduls (T-17, api.md »budget«).

Request/Response-Hüllen für Topf-CRUD (inkl. Extra-Feld-Defs = ``FormFieldDef``,
config_schemas §5.7), Antrag→Topf-Zuordnung und die Rollup-Statistik. Geld konsequent
als ``Decimal`` (numeric(12,2)); Stufen als ``Literal`` über :data:`STAGES`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.shared.config_schemas import FormFieldDef

Stage = Literal["requested", "reserved", "approved", "paid"]


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- pots
class BudgetPotCreate(_CamelModel):
    """Neuen Topf anlegen (+ optionale Extra-Felder)."""

    gremium_id: UUID = Field(alias="gremiumId")
    name: str = Field(min_length=1)
    total: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    period: str | None = None
    active: bool = True
    fields: list[FormFieldDef] = Field(default_factory=list)


class BudgetPotUpdate(_CamelModel):
    """Topf teil-aktualisieren. ``fields`` (falls gesetzt) **ersetzt** die Extra-Felder."""

    name: str | None = Field(default=None, min_length=1)
    total: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    period: str | None = None
    active: bool | None = None
    fields: list[FormFieldDef] | None = None


class BudgetPotOut(_CamelModel):
    """Topf-Stammdaten + Extra-Felder."""

    id: UUID
    gremium_id: UUID = Field(alias="gremiumId")
    name: str
    total: Decimal | None
    currency: str
    period: str | None
    active: bool
    fields: list[FormFieldDef]


class PotUsageOut(_CamelModel):
    """Auslastung eines Topfs (Summen je Stufe + freier Rest)."""

    budget_pot_id: UUID = Field(alias="budgetPotId")
    period: str | None
    total: Decimal | None
    currency: str
    requested: Decimal
    reserved: Decimal
    approved: Decimal
    paid: Decimal
    committed: Decimal
    available: Decimal | None


class BudgetPotDetailOut(_CamelModel):
    """Einzelner Topf inkl. live berechneter Auslastung."""

    pot: BudgetPotOut
    usage: PotUsageOut


# ----------------------------------------------------------------------- assign
class AssignRequest(_CamelModel):
    """Antrag einem Topf zuordnen (``budgetPotId=null`` → Zuordnung lösen)."""

    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    note: str | None = None


class AssignOut(_CamelModel):
    """Ergebnis einer Zuordnung."""

    application_id: UUID = Field(alias="applicationId")
    gremium_id: UUID | None = Field(alias="gremiumId")
    budget_pot_id: UUID | None = Field(alias="budgetPotId")
    stage: Stage | None
    amount: Decimal | None
    currency: str | None


# ------------------------------------------------------------------------ stats
class StatusBucketOut(_CamelModel):
    """Eine Zelle der Statusverteilung (Gremium × State)."""

    gremium_id: UUID | None = Field(alias="gremiumId")
    state_id: UUID | None = Field(alias="stateId")
    count: int


class BudgetStatsOut(_CamelModel):
    """Rollup-Statistik (api.md ``GET /budget/stats``): Auslastung + Statusverteilung."""

    pots: list[PotUsageOut]
    status_distribution: list[StatusBucketOut] = Field(alias="statusDistribution")
