"""Audit-Tabelle ``audit_entry`` (data-model §1, security.md §4).

Append-only Hash-Kette. ``id`` ist ``bigserial`` (Generierungs-Reihenfolge = Ketten-
Reihenfolge). UPDATE/DELETE werden zusätzlich DB-seitig per Trigger abgelehnt
(Migration ``0005`` + Least-Privilege-Grant ``audit_writer``); kein ORM-Mutate-Pfad.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuditEntry(Base):
    __tablename__ = "audit_entry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # actor: Principal-``sub`` bzw. ``None`` für System-/anonyme Vorgänge.
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # data: NUR id-Referenzen/Metadaten — keine PII-Rohwerte (security.md §4).
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (
        Index("ix_audit_entry_at", "at"),
        Index("ix_audit_entry_target_type_target_id", "target_type", "target_id"),
    )
