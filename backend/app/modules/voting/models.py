"""Voting tables: Vote, Ballot, VotedMarker, SecretBallot.

* Vote - a vote on an application; ``config`` (JSONB) is a VoteConfig
  (options/majority/quorum/secret/allowChange/tieBreak). ``eligible_group`` is
  the group key (OIDC group or gremium scope) that ``require_group`` checks.
* Ballot - one vote. ``UNIQUE(vote_id, voter_sub)`` prevents a double vote
  atomically in the DB; ``allowChange`` updates the existing row until close.
* VotedMarker / SecretBallot - secret path (``secret=true``): the identity
  (``voted_marker``) is stored separately from the choice (``secret_ballot``,
  without identity) so ``choice`` cannot be traced back to the voter.

``eligible_count`` is the authoritative eligible-voter count (roster) set at creation.
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
    """A vote on an application (optionally bound to a meeting)."""

    __tablename__ = "vote"

    # NULL = generic resolution question of a free-text agenda item (no application);
    # such a vote fires no flow branch and is only shown in the protocol. On application
    # agenda items it is the application whose pass/fail branch fires on close.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    # SET NULL: deleting the meeting detaches the (async) vote instead of cascading it.
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting.id", ondelete="SET NULL"), nullable=True
    )
    # Agenda item the vote is bound to (live vote). CASCADE: dropping the TOP drops
    # the generic resolution question with it.
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_agenda_item.id", ondelete="CASCADE"), nullable=True
    )
    eligible_group: Mapped[str] = mapped_column(Text)
    # Vote question shown on the protocol snippet. NULL = no explicit question.
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB)
    # Authoritative eligible-voter count (roster) = denominator of the percent quorum.
    # NULL = unknown -> percent quorum is fail-closed (never met).
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
        # ``cancelled``: the application left the vote state manually (vote aborted),
        # so the vote is cancelled without a result.
        CheckConstraint(
            "status IN ('draft','open','closed','cancelled')", name="vote_status"
        ),
        CheckConstraint(
            "result IS NULL OR result IN ('passed','rejected','tie')",
            name="vote_result",
        ),
        Index("ix_vote_application_id", "application_id"),
        Index("ix_vote_status_closes_at", "status", "closes_at"),
    )


class Ballot(UUIDPkMixin, Base):
    """One (open) ballot. ``choice`` is NULL when ``secret=true`` (see SecretBallot)."""

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
    """Secret path: 'has voted' marker without ``choice`` (identity kept apart)."""

    __tablename__ = "voted_marker"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )
    voter_sub: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("vote_id", "voter_sub", name="uq_voted_marker_vote_voter"),
    )


class SecretBallot(UUIDPkMixin, Base):
    """Secret path: only ``choice`` (no identity), not traceable to the voter.

    Deliberately timestamp-free: a precise ``at`` would be a correlation channel
    that could re-link ``choice`` to a voter via an external sub+time source. Only
    ``vote_id`` membership matters for the aggregate.
    """

    __tablename__ = "secret_ballot"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )
    choice: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_secret_ballot_vote_id", "vote_id"),)
