"""Privacy module API schemas (camelCase JSON, populate-by-name)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.shared.schemas import FrozenCamelModel

SubjectType = Literal["applicant", "principal"]
ErasureStatus = Literal["open", "executed", "rejected"]


class ErasureRequestOut(FrozenCamelModel, frozen=True):
    """An erasure request."""

    id: UUID
    created_at: datetime = Field(alias="createdAt")
    subject_type: SubjectType = Field(alias="subjectType")
    application_id: UUID | None = Field(default=None, alias="applicationId")
    principal_id: UUID | None = Field(default=None, alias="principalId")
    email: str | None = None
    status: ErasureStatus
    requested_by: str | None = Field(default=None, alias="requestedBy")
    handled_by: str | None = Field(default=None, alias="handledBy")
    handled_at: datetime | None = Field(default=None, alias="handledAt")
    reason: str | None = None


class ErasureRejectBody(FrozenCamelModel, frozen=True):
    """Rejection reason. The notification to the subject shows it."""

    reason: str | None = None


class PrivacySettingsOut(FrozenCamelModel, frozen=True):
    """The privacy settings."""

    default_retention_months: int = Field(alias="defaultRetentionMonths")


class PrivacySettingsUpdate(FrozenCamelModel, frozen=True):
    """New privacy settings."""

    default_retention_months: int = Field(alias="defaultRetentionMonths", ge=1)


class EmailErasureBody(FrozenCamelModel, frozen=True):
    """The address whose applications and ticket reports go."""

    email: str = Field(min_length=1)


class EmailErasureOut(FrozenCamelModel, frozen=True):
    """What the erasure of an address anonymized.

    ``principalId`` names an account under the address. Its erasure is a separate
    step, because it deactivates the account.
    """

    applications: int
    tickets: int
    principal_id: UUID | None = Field(default=None, alias="principalId")
