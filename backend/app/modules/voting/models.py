"""Voting tables: Vote, Ballot, VotedMarker, SecretBallot.

* Vote - a vote on an application. ``config`` (JSONB) holds a VoteConfig
  (options/majority/quorum/secret/allowChange/tieBreak). ``eligible_group`` is the
  group key (OIDC group or gremium scope) that ``require_group`` checks.
* Ballot - one cast vote. ``UNIQUE(vote_id, voter_sub)`` blocks a double vote
  atomically in the DB. ``allowChange`` updates the existing row until close.
* VotedMarker / SecretBallot - the secret path (``secret=true``). The identity goes to
  ``voted_marker`` and the choice to ``secret_ballot`` without an identity. Nobody can
  trace ``choice`` back to the voter.

``eligible_count`` is the authoritative eligible-voter count (roster). The create call
sets it.
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

    # A NULL value marks a generic resolution question of a free-text agenda item with
    # no application. Such a vote fires no flow branch and appears only in the protocol.
    # On an application agenda item this is the application whose pass or fail branch
    # fires on close.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    # SET NULL: a delete of the meeting detaches the (async) vote and does not cascade.
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting.id", ondelete="SET NULL"), nullable=True
    )
    # The agenda item that the vote belongs to (live vote). CASCADE: a delete of the
    # agenda item also removes the generic resolution question.
    agenda_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("meeting_agenda_item.id", ondelete="CASCADE"), nullable=True
    )
    eligible_group: Mapped[str] = mapped_column(Text)
    # The vote question that the protocol snippet shows. NULL means no explicit question.
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB)
    # Authoritative eligible-voter count (roster). It is the denominator of the percent
    # quorum. A NULL value means unknown, so the percent quorum stays fail-closed and
    # never counts as met.
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
        # ``cancelled``: the application left the vote state manually, so the vote ends
        # without a result.
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

    This table has no timestamp on purpose. A precise ``at`` value would open a
    correlation channel. An attacker with an external source of sub and time could
    then re-link ``choice`` to a voter. Only ``vote_id`` membership matters for the
    aggregate.
    """

    __tablename__ = "secret_ballot"

    vote_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vote.id", ondelete="CASCADE")
    )
    choice: Mapped[str] = mapped_column(Text)

    __table_args__ = (Index("ix_secret_ballot_vote_id", "vote_id"),)
