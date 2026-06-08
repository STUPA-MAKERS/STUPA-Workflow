"""API-Schemata des applications-Moduls (T-12, api.md §3/§5).

Request/Response-Hüllen für Antrag-CRUD, Timeline, Versionshistorie, Liste und
Kommentare. PII (``applicant``-Mail/Name) wird **nur** an berechtigte Principals
oder den Antragsteller selbst ausgegeben (``ApplicationOut.applicant``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.applications.diff import DataDiff
from app.shared.altcha import AltchaSolutionStr
from app.shared.i18n import DEFAULT_LANG, I18nMap, Lang


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
class ApplicationCreate(_CamelModel):
    """Antrag anlegen (api.md §5). ``data`` wird gegen die effektive Form validiert.

    Anonyme Einreichung: ``altcha`` wird serverseitig verifiziert (security.md §7,
    Issue #23) und ``applicantEmail`` ist Pflicht. Eingeloggte Nutzer:innen (#24)
    brauchen **kein** Altcha; ``applicantEmail``/``applicantName`` werden — falls leer
    — aus dem Account abgeleitet. Der Router erzwingt die anonymen Pflichtfelder.
    """

    type_id: UUID = Field(alias="typeId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    data: dict[str, Any]
    # Optional auf Schema-Ebene: für eingeloggte Nutzer:innen aus dem Account ableitbar
    # (#24). Für anonyme Einreichung erzwingt der Router die Pflicht (422).
    applicant_email: EmailStr | None = Field(default=None, alias="applicantEmail")
    applicant_name: str | None = Field(default=None, alias="applicantName")
    lang: Lang = DEFAULT_LANG
    # Strukturell schon im Schema validiert (malformt → 422); kryptografische Prüfung via
    # `require_altcha` (security.md §7, Issue #23). Vgl. `MagicLinkRequest.altcha`.
    altcha: AltchaSolutionStr | None = None


class ApplicationCreated(_CamelModel):
    """201-Antwort auf ``POST /applications`` — nur die ID (+ Mail-Hinweis im FE)."""

    application_id: UUID = Field(alias="applicationId")


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
class StateOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    category: str
    edit_allowed: bool = Field(alias="editAllowed")
    # State-Art (#28) — das FE zeigt z. B. bei ``approval`` Annehmen/Ablehnen-Aktionen.
    kind: str = "normal"


class ApplicantOut(_CamelModel):
    """PII des Antragstellers — nur für Berechtigte sichtbar."""

    email: str | None = None
    name: str | None = None
    anonymized: bool = False


class ApplicationOut(_CamelModel):
    id: UUID
    type_id: UUID = Field(alias="typeId")
    state: StateOut | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    amount: Decimal | None = None
    currency: str | None = None
    data: dict[str, Any]
    version: int
    lang: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    applicant: ApplicantOut | None = None


class ApplicationPatch(_CamelModel):
    """Antragsdaten aktualisieren (neue Version nur wenn ``state.editAllowed``)."""

    data: dict[str, Any]


# --------------------------------------------------------------------------- #
# Timeline / Versions
# --------------------------------------------------------------------------- #
class TimelineEventOut(_CamelModel):
    from_state_id: UUID | None = Field(default=None, alias="fromStateId")
    to_state_id: UUID = Field(alias="toStateId")
    to_state: StateOut | None = Field(default=None, alias="toState")
    actor: str | None = None
    at: datetime
    note: str | None = None


class VersionOut(_CamelModel):
    version: int
    data: dict[str, Any]
    diff: DataDiff | None = None
    changed_by: str | None = Field(default=None, alias="changedBy")
    at: datetime


# --------------------------------------------------------------------------- #
# List
# --------------------------------------------------------------------------- #
class ApplicationListItem(_CamelModel):
    id: UUID
    type_id: UUID = Field(alias="typeId")
    state: StateOut | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    amount: Decimal | None = None
    currency: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


# --------------------------------------------------------------------------- #
# Comments
# --------------------------------------------------------------------------- #
class CommentCreate(_CamelModel):
    body: str = Field(min_length=1)
    visibility: Literal["internal", "public"] = "public"


class CommentOut(_CamelModel):
    id: UUID
    author: str | None = None
    author_kind: Literal["principal", "applicant"] = Field(alias="authorKind")
    body: str
    visibility: Literal["internal", "public"]
    at: datetime
