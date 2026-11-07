"""Wire schemas of the backup admin API.

The output carries metadata only. An archive is never inlined into a response: it
leaves the platform through a short-lived signed URL, and it enters through a
multipart upload.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, Field

from app.shared.schemas import FrozenModel


class BackupOut(FrozenModel, frozen=True):
    """One catalogue row as the admin page shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    status: str
    created_at: datetime = Field(serialization_alias="createdAt")
    finished_at: datetime | None = Field(default=None, serialization_alias="finishedAt")
    created_by: str | None = Field(default=None, serialization_alias="createdBy")
    size_bytes: int | None = Field(default=None, serialization_alias="sizeBytes")
    object_count: int | None = Field(default=None, serialization_alias="objectCount")
    checksum: str | None = None
    note: str | None = None
    app_version: str | None = Field(default=None, serialization_alias="appVersion")
    schema_revision: str | None = Field(default=None, serialization_alias="schemaRevision")
    pinned: bool = False
    error: str | None = None


class BackupListOut(FrozenModel, frozen=True):
    """The catalogue plus the capability flags the page needs to enable its buttons."""

    items: tuple[BackupOut, ...]
    #: False when no age recipient is configured. The page then explains why creating
    #: is off instead of offering a button that always fails.
    enabled: bool
    #: False when no age identity is mounted. Restore and import stay off, because the
    #: platform cannot decrypt its own archives without it.
    restore_enabled: bool = Field(serialization_alias="restoreEnabled")
    retention_count: int = Field(serialization_alias="retentionCount")


class BackupCreate(FrozenModel, frozen=True):
    """Body of `POST /admin/backups`."""

    note: str | None = Field(default=None, max_length=500)


class BackupUpdate(FrozenModel, frozen=True):
    """Body of `PATCH /admin/backups/{id}`: the note and the retention pin."""

    note: str | None = Field(default=None, max_length=500)
    pinned: bool | None = None


class BackupRestoreBody(FrozenModel, frozen=True):
    """Body of `POST /admin/backups/{id}/restore`.

    `confirm` must be the literal string `RESTORE`. The restore replaces the whole
    database, so a stray click on a REST client must not be enough to trigger it.
    """

    confirm: str


class BackupJobOut(FrozenModel, frozen=True):
    """What an enqueue returns: the row to poll."""

    id: UUID
    status: str
