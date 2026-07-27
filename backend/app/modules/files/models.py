"""Attachments: the ``attachment`` table.

One row holds one uploaded file. The binary object lives in MinIO under
``storage_key``, never in the database. ``scanned`` and ``scan_result`` carry the ClamAV
result. The file stays quarantined and nobody can download it until ``scanned`` is true.
On a finding the worker deletes the object, sets ``storage_key`` to NULL and writes the
signature into ``scan_result``.
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

# The database enforces this bound with CHECK(size <= 10485760).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024


class Attachment(UUIDPkMixin, Base):
    """An attachment of an application.

    ``application_id`` cascades. A deleted application removes its attachments.

    Attributes:
        field_key: Optional link to a form field.
        scanned: True after the ClamAV run finishes.
        scan_result: NULL, ``clean``, or the signature of the finding.
        storage_key: NULL after a finding, because the worker removed the object.
    """

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
