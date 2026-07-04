"""API schemas for the applications module.

Request/response shells for application CRUD, timeline, version history, list
and comments. PII (``applicant`` mail/name) is emitted only to authorized
principals or the applicant themselves (``ApplicationOut.applicant``).
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
    """camelCase aliases in JSON; fields populatable by name."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
class ApplicationCreate(_CamelModel):
    """Create an application. ``data`` is validated against the effective form.

    Anonymous submissions: ``altcha`` is verified server-side and
    ``applicantEmail`` is required. Logged-in users need no ALTCHA;
    ``applicantEmail``/``applicantName`` are derived from the account if empty.
    The router enforces the anonymous required fields.
    """

    type_id: UUID = Field(alias="typeId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    data: dict[str, Any]
    # Optional at schema level: derivable from the account for logged-in users.
    # For anonymous submissions the router enforces it (422).
    applicant_email: EmailStr | None = Field(default=None, alias="applicantEmail")
    # Upper bound (anti-DoS): persisted free text (display name) is capped.
    applicant_name: str | None = Field(default=None, alias="applicantName", max_length=256)
    lang: Lang = DEFAULT_LANG
    # Structurally validated in the schema (malformed -> 422); cryptographic
    # verification happens via `require_altcha`.
    altcha: AltchaSolutionStr | None = None


class ApplicationCreated(_CamelModel):
    """201 response to ``POST /applications`` — just the id."""

    application_id: UUID = Field(alias="applicationId")


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
class StateOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    color: str | None = None
    edit_allowed: bool = Field(alias="editAllowed")
    # State kind — the frontend shows e.g. approve/reject actions for ``approval``.
    kind: str = "normal"


class ApplicantOut(_CamelModel):
    """Applicant PII — visible to authorized identities only."""

    email: str | None = None
    name: str | None = None
    anonymized: bool = False


class ApplicationOut(_CamelModel):
    id: UUID
    type_id: UUID = Field(alias="typeId")
    state: StateOut | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    amount: Decimal | None = None
    currency: str | None = None
    data: dict[str, Any]
    version: int
    lang: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    applicant: ApplicantOut | None = None
    # May the requester edit/delete (manager or creator)?
    can_edit: bool = Field(default=False, alias="canEdit")
    # Is the requester the creator (applicant)? Gates the anonymization request
    # (GDPR Art. 17): only the data subject, not administration.
    is_owner: bool = Field(default=False, alias="isOwner")


class ApplicationPatch(_CamelModel):
    """Update application data (new version only if ``state.editAllowed``)."""

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
    # Application title (system title field ``data['title']``) for the list column.
    title: str | None = None
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
    # Hard cap (anti-DoS): keeps a single comment from growing unbounded
    # (DB/mail render); beyond it -> 422.
    body: str = Field(min_length=1, max_length=10_000)
    visibility: Literal["internal", "public"] = "public"


class CommentOut(_CamelModel):
    id: UUID
    author: str | None = None
    author_kind: Literal["principal", "applicant"] = Field(alias="authorKind")
    body: str
    visibility: Literal["internal", "public"]
    at: datetime
    # Whether the requesting viewer wrote this comment (chat alignment in the FE).
    is_own: bool = Field(default=False, alias="isOwn")
