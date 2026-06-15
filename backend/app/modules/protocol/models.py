"""Protokoll-Tabellen (data-model §1 »protocol/protocol_vote_ref«, flows §7, T-22).

* :class:`Protocol` — ein Sitzungsprotokoll, **1:1** an eine ``meeting`` gebunden
  (UNIQUE ``meeting_id`` → ``POST /meetings/{id}/protocol`` ist idempotent: anlegen
  **oder** laden). ``markdown`` ist das versionierte Editor-Backing; ``finalize``
  setzt ``status='final'`` + ``pdf_storage_key``/``sent_at``.
* :class:`ProtocolVoteRef` — eingebettete Abstimmung (``POST /protocols/{id}/votes``).
  UNIQUE(protocol_id, vote_id) macht das Einbetten idempotent (kein Doppel-Snippet).

Wie alle Modul-Tabellen entstehen sie auf einem **frischen** Schema über
``Base.metadata.create_all`` in Migration 0002 (Single-Source via ``app.models``);
für ältere Schemata legt Migration 0013 sie idempotent (``checkfirst``) nach.
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

# Erlaubter Lebenszyklus (data-model §1: draft → rendering → final).
# ``rendering`` = finalize angestoßen, der Worker rendert das PDF im Hintergrund;
# schlägt der Render dauerhaft fehl, fällt das Protokoll auf ``draft`` zurück.
PROTOCOL_STATUSES = ("draft", "rendering", "final")


class Protocol(UUIDPkMixin, TimestampMixin, Base):
    """Sitzungsprotokoll (Markdown-Backing + Finalisierungs-Zustand)."""

    __tablename__ = "protocol"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    markdown: Mapped[str] = mapped_column(Text, server_default="")
    pdf_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Redigierte öffentliche Variante (nur befüllt, wenn ein TOP nicht-öffentlich ist).
    public_pdf_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # pytex CD-Variante (vom Gremium übernommen) → ``protocol-stupa``/``protocol-asta``.
    cd_variant: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','rendering','final')", name="protocol_status"
        ),
        # 1:1 Sitzung ↔ Protokoll: garantiert die Idempotenz von POST .../protocol.
        UniqueConstraint("meeting_id", name="uq_protocol_meeting"),
        Index("ix_protocol_gremium_id", "gremium_id"),
    )


class ProtocolVoteRef(UUIDPkMixin, Base):
    """Eingebettete Abstimmung eines Protokolls (Snippet-Anker, data-model §1)."""

    __tablename__ = "protocol_vote_ref"

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("protocol.id", ondelete="CASCADE")
    )
    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )

    __table_args__ = (
        # Einbetten ist idempotent: ein Vote referenziert ein Protokoll höchstens einmal.
        UniqueConstraint("protocol_id", "vote_id", name="uq_protocol_vote_ref"),
        Index("ix_protocol_vote_ref_protocol_id", "protocol_id"),
    )
