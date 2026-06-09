"""Voting-Tabellen (data-model §5.3 »Voting«, flows §4).

* :class:`Vote` — Abstimmung zu einem Antrag; ``config`` (JSONB) = :class:`VoteConfig`
  (Optionen/Mehrheitsregel/Quorum/secret/allowChange/tieBreak). ``eligible_group`` ist
  der Gruppen-Key (OIDC-Gruppe oder Gremium-Scope), gegen den ``require_group`` prüft.
* :class:`Ballot` — eine Stimme. **``UNIQUE(vote_id, voter_sub)``** verhindert die
  Doppelstimme atomar auf DB-Ebene (data-model §2); ``allowChange`` aktualisiert die
  bestehende Zeile bis zum Schluss.
* :class:`VotedMarker` / :class:`SecretBallot` — Geheim-Pfad (``secret=true``): die
  Identität (``voted_marker``) wird von der Stimme (``secret_ballot``, ohne Identität)
  getrennt gespeichert, sodass ``choice`` nicht zum Wähler rückführbar ist.

Auf einem **frischen** Schema entstehen die Tabellen über ``Base.metadata.create_all``
in Migration 0002 (Single-Source via ``app.models``); für bereits ältere Schemata legt
Migration 0007 sie **idempotent** (``checkfirst``) nach. ``eligible_count`` ist die
maßgebliche Stimmberechtigten-Zahl (Roster), die beim Anlegen gesetzt wird.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Vote(UUIDPkMixin, CreatedAtMixin, Base):
    """Abstimmung zu einem Antrag (optional an eine Sitzung gebunden, T-16)."""

    __tablename__ = "vote"

    # NULL = generische Beschlussfrage eines Freitext-TOP (kein Antrag); dann fällt der
    # Vote KEINEN Flow-Branch, sondern wird nur im Protokoll ausgewiesen. Bei Antrags-
    # TOPs ist es der Antrag, dessen pass/fail-Branch beim Close gefeuert wird.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    # `meeting` existiert ab T-16 (Live-Vote); die FK wird hier nun gesetzt (frische
    # Schemata via create_all, ältere via Migration 0008). SET NULL: gelöschte Sitzung
    # entkoppelt den (Async-)Vote, statt ihn zu kaskadieren.
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting.id", ondelete="SET NULL"), nullable=True
    )
    # An welchen Tagesordnungspunkt die Abstimmung gebunden ist (Live-Vote). CASCADE:
    # entfällt der TOP, entfällt die generische Beschlussfrage mit.
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_agenda_item.id", ondelete="CASCADE"), nullable=True
    )
    eligible_group: Mapped[str] = mapped_column(Text)
    # Beschluss-/Abstimmungsfrage (Live-Vote): »Worüber wird abgestimmt?« — wird im
    # Protokoll am Abstimmungs-Snippet ausgewiesen. NULL = keine explizite Frage.
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB)
    # Maßgebliche Zahl der Stimmberechtigten (Roster der Gruppe/des Gremiums) — Nenner
    # des Prozent-Quorums. NULL = unbekannt → Prozent-Quorum fail-closed (nie erfüllt).
    eligible_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opens_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("state.id", ondelete="SET NULL"), nullable=True
    )
    opens_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closes_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_branch_transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transition.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','open','closed')", name="vote_status"
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('passed','rejected','tie')",
            name="vote_result",
        ),
        Index("ix_vote_application_id", "application_id"),
        Index("ix_vote_status_closes_at", "status", "closes_at"),
    )


class Ballot(UUIDPkMixin, Base):
    """Eine (offene) Stimme. ``choice`` ist bei ``secret=true`` NULL (s. SecretBallot)."""

    __tablename__ = "ballot"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )
    voter_sub: Mapped[str] = mapped_column(Text)
    choice: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("vote_id", "voter_sub", name="uq_ballot_vote_voter"),
    )


class VotedMarker(UUIDPkMixin, Base):
    """Geheim-Pfad: »hat abgestimmt« ohne ``choice`` (Identität getrennt von Stimme)."""

    __tablename__ = "voted_marker"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )
    voter_sub: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("vote_id", "voter_sub", name="uq_voted_marker_vote_voter"),
    )


class SecretBallot(UUIDPkMixin, Base):
    """Geheim-Pfad: nur ``choice`` (keine Identität) — nicht auf den Wähler rückführbar.

    **Bewusst zeitstempel-frei.** Ein präziser ``at`` wäre ein Korrelationskanal:
    gegen eine externe sub+Zeit-Quelle (Audit/Proxy-Log) ließe sich ``choice↔voter``
    rekonstruieren. Die Reihenfolge der anonymen Stimmen ist nicht beobachtbar
    (nur die ``vote_id``-Zugehörigkeit zählt fürs Aggregat)."""

    __tablename__ = "secret_ballot"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )
    choice: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_secret_ballot_vote_id", "vote_id"),)
