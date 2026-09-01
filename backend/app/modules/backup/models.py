"""Backups: the ``backup`` table.

The table holds one row per archive. It is a catalogue, not the data: the archive
itself lives in the backup bucket in MinIO under ``storage_key``, age-encrypted. The
row carries only the metadata that the admin page lists, plus the job state that
``GET /admin/backups/{id}`` polls: ``pending`` → ``running`` → ``done``/``failed``.

``kind`` records why the archive exists. ``manual`` comes from the button, ``scheduled``
from the nightly cron, ``pre_restore`` from the safety copy that every restore takes
before it replaces anything, and ``imported`` from an uploaded file. The kind drives
retention: ``pre_restore`` and a pinned row never get pruned.

``error`` holds a short failure code and never a path or a stacktrace, so nothing about
the container leaks into the admin page.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin

BACKUP_STATUSES = ("pending", "running", "done", "failed")
BACKUP_KINDS = ("manual", "scheduled", "pre_restore", "imported")

# Names inside the archive tar. `restore` refuses an archive that misses either one.
ARCHIVE_DUMP_NAME = "db.dump"
ARCHIVE_OBJECT_PREFIX = "objects/"
ARCHIVE_MANIFEST_NAME = "manifest.json"


class Backup(UUIDPkMixin, TimestampMixin, Base):
    """One backup archive plus its job state."""

    __tablename__ = "backup"

    # Each of these carries a Python-side `default` next to the `server_default`. The
    # server default alone only materializes on INSERT, and SQLAlchemy would then have
    # to re-SELECT the row to answer `row.pinned` in the same request. The routes read
    # these fields straight after the flush, so the value has to be there already.
    kind: Mapped[str] = mapped_column(Text, default="manual", server_default="manual")
    status: Mapped[str] = mapped_column(Text, default="pending", server_default="pending")
    # OIDC ``sub`` of whoever pressed the button. NULL for the nightly cron, which has
    # no principal. It is a sub rather than a principal id on purpose: a restore
    # replaces the principal table, and a catalogue row must survive an actor that the
    # restored state no longer knows.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # sha256 of the encrypted archive. The import path checks it, so a truncated
    # upload fails before a restore ever reads it.
    checksum: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Free note from the create dialog, and the app version the archive came from.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The alembic head the dump was taken at. A restore warns when it differs from
    # the head the code expects, because the schema then does not match.
    schema_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A pinned archive survives every retention run.
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('pending','running','done','failed')", name="backup_status"),
        CheckConstraint(
            "kind IN ('manual','scheduled','pre_restore','imported')", name="backup_kind"
        ),
        Index("ix_backup_created_at", "created_at"),
        Index("ix_backup_status", "status"),
    )

    def touch_finished(self, now: datetime) -> None:
        """Set ``finished_at`` after the worker finishes the job (done or failed)."""
        self.finished_at = now
