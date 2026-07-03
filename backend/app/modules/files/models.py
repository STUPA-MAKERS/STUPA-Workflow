"""Attachments: ``attachment``.

One row per uploaded file. The binary object lives in MinIO (``storage_key``), never
in the DB. ``scanned``/``scan_result`` carry the ClamAV result: quarantined (no
download) until ``scanned``; on a finding the object is deleted (``storage_key`` →
NULL) and ``scan_result`` holds the signature.
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

# DB-side upper bound (CHECK(size <= 10485760)).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class Attachment(UUIDPkMixin, Base):
    """Application attachment. ``application_id`` CASCADE: deleting the app cleans up.

    ``field_key`` optionally links to a form field. ``scanned`` = ClamAV run finished;
    ``scan_result`` = NULL/``clean``/signature. ``storage_key`` is set to NULL on a
    finding (object removed)."""

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
