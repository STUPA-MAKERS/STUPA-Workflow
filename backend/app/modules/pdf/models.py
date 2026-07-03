"""Render jobs: the ``render_job`` table.

One row per triggered PDF render. The async path needs a persistent status that
``GET /jobs/{id}`` reads: ``pending`` → ``running`` → ``done``/``failed``. The PDF
itself lives in MinIO (``storage_key``), never in the DB; ``error`` holds a short,
path-free failure code (no leak).

``idempotency_key`` (UNIQUE, NULL allowed) carries flow-action idempotency
(``exportPdf``): the same status event must not create a second job. The REST path
(``POST /applications/{id}/pdf``) leaves the key NULL, so every call is a fresh,
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

# Allowed job statuses (pending/done/failed; running = in progress).
JOB_STATUSES = ("pending", "running", "done", "failed")

# The only job kind so far; kept as a column so ``/jobs`` can later accept further
# render kinds (e.g. protocol) without a schema change.
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
        # Flow-action idempotency: one status event ⇒ at most one job (NULL = REST path,
        # allowed repeatedly — Postgres treats NULLs in UNIQUE as distinct).
        Index("ix_render_job_idempotency_key", "idempotency_key", unique=True),
    )

    def touch_finished(self, now: datetime) -> None:
        """Set ``finished_at`` (done/failed), worker-side after completion."""
        self.finished_at = now
