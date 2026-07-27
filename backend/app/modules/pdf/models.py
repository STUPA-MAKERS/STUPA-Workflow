"""Render jobs: the ``render_job`` table.

The table holds one row per triggered PDF render. The async path needs a persistent
status that ``GET /jobs/{id}`` reads: ``pending`` → ``running`` → ``done``/``failed``.
The PDF itself lives in MinIO (``storage_key``), never in the DB. ``error`` holds a
short, path-free failure code that leaks nothing.

``idempotency_key`` (UNIQUE, NULL allowed) carries the idempotency of the ``exportPdf``
flow action. The same status event must not create a second job. The REST path
(``POST /applications/{id}/pdf``) leaves the key NULL, so every call is a fresh and
explicit render request.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin

JOB_STATUSES = ("pending", "running", "done", "failed")

# The only job kind so far. It stays a column so ``/jobs`` can accept further render
# kinds later, for example protocol, without a schema change.
JOB_KIND_APPLICATION_PDF = "application_pdf"


class RenderJob(UUIDPkMixin, TimestampMixin, Base):
    """Async render request plus its result/error state."""

    __tablename__ = "render_job"

    kind: Mapped[str] = mapped_column(Text, server_default=JOB_KIND_APPLICATION_PDF)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','running','done','failed')", name="render_job_status"
        ),
        Index("ix_render_job_application_id", "application_id"),
        # Flow-action idempotency: one status event creates at most one job. NULL marks
        # the REST path and may repeat, because Postgres treats NULLs in a UNIQUE index
        # as distinct.
        Index("ix_render_job_idempotency_key", "idempotency_key", unique=True),
    )

    def touch_finished(self, now: datetime) -> None:
        """Set ``finished_at`` after the worker finishes the job (done or failed)."""
        self.finished_at = now
