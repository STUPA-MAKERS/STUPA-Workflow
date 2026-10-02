"""Audit tables ``audit_entry`` and ``audit_verification``.

``audit_entry`` holds an append-only hash chain. ``id`` is a bigserial, so the insert
order equals the chain order. A database trigger also rejects UPDATE and DELETE.
See migration 0005 and the least-privilege ``audit_writer`` grant. There is no ORM
path that mutates a row.

``audit_verification`` holds the stored results of the chain check (Z6/O8). The
nightly cron, the restore job and ``POST /admin/audit/verify`` each write one row.
The table is not part of the chain and is not append-only: the service keeps the
newest 100 rows and deletes the older rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPkMixin

# What started a stored chain check.
VerificationTrigger = Literal["cron", "manual", "restore"]
VERIFICATION_TRIGGERS: tuple[VerificationTrigger, ...] = ("cron", "manual", "restore")

# Why a chain check failed. The values are the ``reason`` of ``ChainVerification``.
ChainBreak = Literal["prev_hash_mismatch", "hash_mismatch"]
CHAIN_BREAKS: tuple[ChainBreak, ...] = ("prev_hash_mismatch", "hash_mismatch")

# The number of stored chain checks that the service keeps. The prune keeps the first
# failed check of each break and the newest check of each trigger in addition to these
# rows.
VERIFICATION_KEEP = 100

# The minimum time between two manual chain checks. A manual check reads the whole
# log inside an API request.
MANUAL_VERIFICATION_COOLDOWN = timedelta(minutes=5)


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


class AuditVerification(UUIDPkMixin, Base):
    """One stored result of a full chain check (Z6/O8).

    ``broken_at`` is the id of the first broken ``audit_entry`` row. It has no
    foreign key on purpose: the row it names is the one that is suspect, and a
    restore can replace the whole chain.
    """

    __tablename__ = "audit_verification"

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid: Mapped[bool] = mapped_column(Boolean)
    checked: Mapped[int] = mapped_column(BigInteger)
    broken_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(Text)
    # The principal ``sub`` for a manual or restore run. NULL for the cron.
    triggered_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("trigger IN ('cron','manual','restore')", name="trigger"),
        CheckConstraint(
            "reason IS NULL OR reason IN ('prev_hash_mismatch','hash_mismatch')",
            name="reason",
        ),
        # A valid chain has no break. A broken chain names its reason.
        CheckConstraint("valid = (reason IS NULL)", name="valid_reason"),
    )


# The tile reads the newest row, so the index sorts descending. It sits outside the
# class body, because only the mapped attribute has ``desc()``.
Index("ix_audit_verification_started_at", AuditVerification.started_at.desc())
