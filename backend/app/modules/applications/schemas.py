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
from app.shared.i18n import I18nMap


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
class ApplicationCreate(_CamelModel):
    """Antrag anlegen (öffentlich, api.md §5). ``data`` wird gegen die effektive
    Form validiert; ``altcha`` ist im Contract reserviert (Verifikation: Captcha-Task)."""

    type_id: UUID = Field(alias="typeId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    data: dict[str, Any]
    applicant_email: EmailStr = Field(alias="applicantEmail")
    applicant_name: str | None = Field(default=None, alias="applicantName")
    lang: Literal["de", "en"] = "de"
    altcha: str | None = None


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
