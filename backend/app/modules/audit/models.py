"""Audit table ``audit_entry``.

The table holds an append-only hash chain. ``id`` is a bigserial, so the insert
order equals the chain order. A database trigger also rejects UPDATE and DELETE.
See migration 0005 and the least-privilege ``audit_writer`` grant. There is no ORM
path that mutates a row.
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
    # The principal ``sub``, or ``None`` for a system or anonymous operation.
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Holds id references and metadata ONLY. Never put a raw PII value here.
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (
        Index("ix_audit_entry_at", "at"),
        Index("ix_audit_entry_target_type_target_id", "target_type", "target_id"),
    )
