"""API schemas for the ``config_revision`` module.

These are the read views for the version sidebar and the field diff. The diff uses
the same ``DataDiff`` shape as the application detail.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.applications.diff import DataDiff
from app.modules.config_revision.models import ConfigRevision


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ConfigRevisionOut(_CamelModel):
    """One config snapshot (sidebar row)."""

    id: UUID
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")
    version: int
    at: datetime
    # OIDC ``sub`` of the actor plus the resolved display name, as in the audit log.
    created_by: str | None = Field(default=None, alias="createdBy")
    created_by_name: str | None = Field(default=None, alias="createdByName")
    # True for the newest state of the entity, which is the live one.
    is_current: bool = Field(default=False, alias="isCurrent")

    @classmethod
    def from_row(
        cls,
        row: ConfigRevision,
        *,
        created_by_name: str | None = None,
        is_current: bool = False,
    ) -> ConfigRevisionOut:
        return cls(
            id=row.id,
            entityType=row.entity_type,
            entityId=row.entity_id,
            version=row.version,
            at=row.at,
            createdBy=row.created_by,
            createdByName=created_by_name,
            isCurrent=is_current,
        )


class ConfigRevisionDiffOut(_CamelModel):
    """Field diff of a snapshot against its predecessor."""

    id: UUID
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")
    version: int
    prev_version: int | None = Field(default=None, alias="prevVersion")
    diff: DataDiff
