"""Render-Jobs: ``render_job`` (T-20, api.md »pdf«).

Eine Zeile je angestoßenem PDF-Render. Der asynchrone Pfad (flows §6) braucht einen
persistenten Status, den ``GET /jobs/{id}`` ausliest: ``pending`` → ``running`` →
``done``/``failed``. Das PDF selbst liegt in MinIO (``storage_key``), nie in der DB;
``error`` hält eine **kurze, pfadfreie** Fehlerkennung (security.md §2: kein Leak).

``idempotency_key`` (UNIQUE, NULL erlaubt) trägt die Flow-Action-Idempotenz
(``exportPdf``): derselbe Status-Event darf **keinen** zweiten Job erzeugen. Der
REST-Pfad (``POST /applications/{id}/pdf``) lässt den Key NULL → jeder Aufruf ist ein
frischer, expliziter Render-Wunsch.
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

# Erlaubte Job-Status (api.md »pdf«: pending/done/failed; running = in Arbeit).
JOB_STATUSES = ("pending", "running", "done", "failed")

# Bislang einzige Job-Art; als Spalte geführt, damit ``/jobs`` später weitere
# Render-Arten (z. B. Protokoll, T-22) ohne Schema-Änderung aufnehmen kann.
JOB_KIND_APPLICATION_PDF = "application_pdf"


class RenderJob(UUIDPkMixin, TimestampMixin, Base):
    """Asynchroner Render-Auftrag + sein Ergebnis-/Fehlerzustand."""

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
        # Flow-Action-Idempotenz: ein Status-Event ⇒ höchstens ein Job (NULL = REST-Pfad,
        # mehrfach erlaubt — Postgres behandelt NULLs in UNIQUE als verschieden).
        Index("ix_render_job_idempotency_key", "idempotency_key", unique=True),
    )

    def touch_finished(self, now: datetime) -> None:
        """``finished_at`` setzen (done/failed) — Worker-seitig nach Abschluss."""
        self.finished_at = now
