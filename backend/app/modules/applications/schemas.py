"""API schemas for the applications module.

These models shape the requests and the responses for application CRUD, the
timeline, the version history, the list and the comments. The API emits the PII
in ``ApplicationOut.applicant`` only to an authorized principal or to the
applicant.
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
    """Base model with camelCase aliases in JSON.

    The fields also populate by their Python name.
    """

    model_config = ConfigDict(populate_by_name=True)


class ApplicationCreate(_CamelModel):
    """Create an application.

    The server validates ``data`` against the effective form. An anonymous
    submission must carry ``altcha`` and ``applicantEmail``. The server verifies
    the ALTCHA solution. A logged-in user needs no ALTCHA. The server derives an
    empty ``applicantEmail`` or ``applicantName`` from the account. The router
    enforces the fields that an anonymous submission requires.
    """

    type_id: UUID = Field(alias="typeId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    data: dict[str, Any]
    # Optional in the schema, because the account supplies it for a logged-in
    # user. For an anonymous submission the router enforces it and answers 422.
    applicant_email: EmailStr | None = Field(default=None, alias="applicantEmail")
    # Anti-DoS cap on the stored free text of the display name.
    applicant_name: str | None = Field(default=None, alias="applicantName", max_length=256)
    lang: Lang = DEFAULT_LANG
    # The schema validates the structure and answers 422 for a malformed value.
    # `require_altcha` runs the cryptographic verification.
    altcha: AltchaSolutionStr | None = None


class ApplicationCreated(_CamelModel):
    """201 response of ``POST /applications``, with the new id only."""

    application_id: UUID = Field(alias="applicationId")


class StateOut(_CamelModel):
    id: UUID
    key: str
    label: I18nMap
    color: str | None = None
    edit_allowed: bool = Field(alias="editAllowed")
    # State kind. The frontend shows approve and reject actions for ``approval``.
    kind: str = "normal"


class ApplicantOut(_CamelModel):
    """Applicant PII, visible to an authorized identity only."""

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
    # True when the requester may edit or delete: a manager or the creator.
    can_edit: bool = Field(default=False, alias="canEdit")
    # True when the requester is the creator, that is the applicant. This gates
    # the anonymization request (GDPR Art. 17). Only the data subject may ask,
    # never the administration.
    is_owner: bool = Field(default=False, alias="isOwner")


class ApplicationPatch(_CamelModel):
    """Update the application data.

    A new version follows only when ``state.editAllowed`` is true.
    """

    data: dict[str, Any]


class ApplicantPatch(_CamelModel):
    """Correct the applicant name or email.

    An omitted field stays unchanged. The email is the magic-link and
    notification target, so a typo locks the applicant out of the application.
    An anonymized applicant is not patchable.
    """

    email: EmailStr | None = None
    name: str | None = Field(default=None, max_length=256)


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


class ApplicationListItem(_CamelModel):
    id: UUID
    type_id: UUID = Field(alias="typeId")
    # Title for the list column, from the system title field ``data['title']``.
    title: str | None = None
    state: StateOut | None = None
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    budget_pot_id: UUID | None = Field(default=None, alias="budgetPotId")
    amount: Decimal | None = None
    currency: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class CommentCreate(_CamelModel):
    # Anti-DoS cap. It stops one comment from growing without a bound in the
    # database and in the mail render. A longer body answers 422.
    body: str = Field(min_length=1, max_length=10_000)
    visibility: Literal["internal", "public"] = "public"


class CommentPatch(_CamelModel):
    """Replace the body of a comment in place.

    The visibility is not patchable: a public comment is already out, so use
    the delete instead.
    """

    body: str = Field(min_length=1, max_length=10_000)


class CommentOut(_CamelModel):
    id: UUID
    author: str | None = None
    author_kind: Literal["principal", "applicant"] = Field(alias="authorKind")
    body: str
    visibility: Literal["internal", "public"]
    at: datetime
    # True when the requesting viewer wrote the comment. The frontend aligns the
    # chat bubble by this flag.
    is_own: bool = Field(default=False, alias="isOwn")
