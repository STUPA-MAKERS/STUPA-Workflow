"""ORM-Modelle für DSGVO/Privacy.

* :class:`PrivacySettings` — plattformweite Single-Row-Config (id=1): globaler
  Aufbewahrungs-Default in Monaten (DSB-Platzhalter 24), admin-gepflegt.
* :class:`ErasureRequest` — Löschantrags-Queue (DSGVO Art. 17): Antragsteller-
  Selbstauskunft per Magic-Link bzw. Admin-Anlage; Status open/executed/rejected.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class PrivacySettings(Base):
    """Plattformweite DSGVO-Config (Single-Row id=1, admin-gepflegt über /admin/privacy)."""

    __tablename__ = "privacy_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # DSB-Platzhalter: Standard-Aufbewahrung in Monaten (Finanzordnung bestätigen).
    default_retention_months: Mapped[int] = mapped_column(
        Integer, server_default="24", default=24
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="privacy_settings_singleton"),
        CheckConstraint(
            "default_retention_months >= 1", name="default_retention_months_min"
        ),
    )


class ErasureRequest(UUIDPkMixin, CreatedAtMixin, Base):
    """Löschantrag (DSGVO Art. 17). ``application_id``/``principal_id`` per FK
    ``ON DELETE SET NULL`` — der Queue-Eintrag bleibt als Nachweis, auch wenn das
    Subjekt hart gelöscht wird."""

    __tablename__ = "erasure_request"

    subject_type: Mapped[str] = mapped_column(Text)
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    requested_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "subject_type IN ('applicant','principal')",
            name="erasure_request_subject_type",
        ),
        CheckConstraint(
            "status IN ('open','executed','rejected')", name="erasure_request_status"
        ),
        Index("ix_erasure_request_status", "status"),
    )
