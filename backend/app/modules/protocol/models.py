"""Protocol tables.

* :class:`Protocol` — one meeting's minutes, 1:1 to ``meeting`` (UNIQUE
  ``meeting_id`` makes ``POST /meetings/{id}/protocol`` idempotent: create or
  load). ``markdown`` backs the editor; ``finalize`` sets ``status='final'``
  plus ``pdf_storage_key``/``sent_at``.
* :class:`ProtocolVoteRef` — an embedded vote; UNIQUE(protocol_id, vote_id)
  makes embedding idempotent (no duplicate snippets).
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin, UUIDPkMixin

# Lifecycle: draft → rendering → final. ``rendering`` = finalize triggered and
# the worker renders in the background; a permanently failed render falls back to ``draft``.
PROTOCOL_STATUSES = ("draft", "rendering", "final")


class Protocol(UUIDPkMixin, TimestampMixin, Base):
    """Meeting minutes (Markdown backing + finalization state)."""

    __tablename__ = "protocol"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    markdown: Mapped[str] = mapped_column(Text, server_default="")
    pdf_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Redacted public variant (only set when an agenda item is non-public).
    public_pdf_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # pytex CD variant (taken from the gremium), e.g. ``protocol-stupa``/``protocol-asta``.
    cd_variant: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','rendering','final')", name="protocol_status"
        ),
        # 1:1 meeting ↔ protocol: guarantees idempotency of POST .../protocol.
        UniqueConstraint("meeting_id", name="uq_protocol_meeting"),
        Index("ix_protocol_gremium_id", "gremium_id"),
    )


class ProtocolVoteRef(UUIDPkMixin, Base):
    """Embedded vote of a protocol (snippet anchor)."""

    __tablename__ = "protocol_vote_ref"

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocol.id", ondelete="CASCADE")
    )
    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )

    __table_args__ = (
        # Embedding is idempotent: a vote references a protocol at most once.
        UniqueConstraint("protocol_id", "vote_id", name="uq_protocol_vote_ref"),
        Index("ix_protocol_vote_ref_protocol_id", "protocol_id"),
    )
