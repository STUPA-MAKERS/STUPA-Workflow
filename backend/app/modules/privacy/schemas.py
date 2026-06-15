"""API-Schemata des Privacy-Moduls (camelCase im JSON, per Name befüllbar)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SubjectType = Literal["applicant", "principal"]
ErasureStatus = Literal["open", "executed", "rejected"]


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ErasureRequestOut(_CamelModel):
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


class ErasureRejectBody(_CamelModel):
    """Ablehnungsgrund (für die Benachrichtigung an die betroffene Person)."""

    reason: str | None = None


class PrivacySettingsOut(_CamelModel):
    default_retention_months: int = Field(alias="defaultRetentionMonths")


class PrivacySettingsUpdate(_CamelModel):
    default_retention_months: int = Field(alias="defaultRetentionMonths", ge=1)
