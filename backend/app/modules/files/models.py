"""Anhänge: ``attachment`` (data-model §1, security.md §6).

Eine Zeile je hochgeladene Datei. Das Binär-Objekt liegt in MinIO (``storage_key``),
nie in der DB. ``scanned``/``scan_result`` tragen das ClamAV-Ergebnis: bis ``scanned``
gilt Quarantäne (kein Download), bei Befund wird das Objekt gelöscht (``storage_key``
→ NULL) und ``scan_result`` hält die Signatur (security.md §6).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPkMixin

# DB-seitige Obergrenze (security.md §6 / data-model: CHECK(size <= 10485760)).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class Attachment(UUIDPkMixin, Base):
    """Antrags-Anhang. ``application_id`` CASCADE: Löschen des Antrags räumt mit auf.

    ``field_key`` verknüpft optional mit einem Formularfeld (data-model). ``scanned`` =
    ClamAV-Lauf abgeschlossen; ``scan_result`` = NULL/``clean``/Signatur. ``storage_key``
    wird bei Befund auf NULL gesetzt (Objekt entfernt)."""

    __tablename__ = "attachment"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    field_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    scan_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_comparison_offer: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"size <= {MAX_ATTACHMENT_BYTES}", name="attachment_size_limit"
        ),
        Index("ix_attachment_application_id", "application_id"),
    )
