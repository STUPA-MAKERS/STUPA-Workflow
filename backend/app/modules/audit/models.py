"""Audit table ``audit_entry``.

Append-only hash chain; ``id`` is bigserial, so insert order equals chain order.
UPDATE/DELETE are additionally rejected DB-side by a trigger (migration 0005 plus
the least-privilege ``audit_writer`` grant); there is no ORM mutate path.
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
    # actor: principal ``sub``, or ``None`` for system/anonymous operations.
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # data: id references/metadata ONLY — never raw PII values.
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    hash: Mapped[bytes] = mapped_column(LargeBinary)

    __table_args__ = (
        Index("ix_audit_entry_at", "at"),
        Index("ix_audit_entry_target_type_target_id", "target_type", "target_id"),
    )
