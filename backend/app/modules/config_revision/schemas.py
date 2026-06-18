"""API-Schemata des config_revision-Moduls (#config-versioning).

Lese-Sichten für die Versions-Sidebar (Liste) und den Feld-Diff (gleiche
``DataDiff``-Form wie das Antrags-Detail, vom FE-``mapDiff`` konsumiert).
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
    """Ein Config-Snapshot (Sidebar-Zeile)."""

    id: UUID
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")
    version: int
    at: datetime
    # Auslöser-``sub`` + aufgelöster Klarname (wie im Audit-Log).
    created_by: str | None = Field(default=None, alias="createdBy")
    created_by_name: str | None = Field(default=None, alias="createdByName")
    # Jüngster Stand der Entität (= aktuell live).
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
    """Feld-Diff eines Snapshots gegen seinen Vorgänger."""

    id: UUID
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")
    version: int
    prev_version: int | None = Field(default=None, alias="prevVersion")
    diff: DataDiff
