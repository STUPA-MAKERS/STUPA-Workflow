"""Meeting-delegation tables.

:class:`MeetingDelegation` — session-bound representation: exactly one outgoing
delegation per (meeting, delegator); the gremium is the meeting's.
``delegate_voting`` additionally transfers the voting right (exclusive transfer,
no duplicate — the delegator is blocked from voting in that meeting).

:class:`DelegationSubstitute` — per-gremium substitute pool: pool members may be
delegated to without the lead-time deadline, even if not gremium members
themselves. ``member_principal_id IS NULL`` = substitute for every member.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class MeetingDelegation(UUIDPkMixin, CreatedAtMixin, Base):
    """Representation for a single meeting; voting right optionally transferred."""

    __tablename__ = "meeting_delegation"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    # Denormalized (= meeting.gremium_id): avoids the join in the hot
    # voting-right check and in "my delegations" queries.
    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    delegator_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    delegate_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    delegate_voting: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Legitimized via the substitute pool (no lead-time deadline on create).
    via_pool: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # ``sub`` of the creator (self-service or admin) — audit anchor.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Exactly one outgoing representation per (meeting, member).
        UniqueConstraint(
            "meeting_id", "delegator_principal_id", name="uq_meeting_delegation_delegator"
        ),
        # At most one voting-right takeover per (meeting, delegate): a principal
        # casts exactly one ballot — a second voting delegation to the same
        # person would silently lapse (transfer, not duplicate).
        Index(
            "uq_meeting_delegation_voting_delegate",
            "meeting_id",
            "delegate_principal_id",
            unique=True,
            postgresql_where=text("delegate_voting"),
        ),
        Index("ix_meeting_delegation_meeting", "meeting_id"),
        Index("ix_meeting_delegation_delegate", "delegate_principal_id"),
    )


class DelegationSubstitute(UUIDPkMixin, CreatedAtMixin, Base):
    """Pool entry: ``substitute`` may represent ``member`` (or every member if
    ``member_principal_id IS NULL``) without the lead-time deadline."""

    __tablename__ = "delegation_substitute"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    # NULL = gremium-wide substitute (represents every member).
    member_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), nullable=True
    )
    substitute_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Gremium-wide entries (member IS NULL) are deduplicated via a partial
        # unique index since UniqueConstraint treats NULLs as distinct.
        UniqueConstraint(
            "gremium_id",
            "member_principal_id",
            "substitute_principal_id",
            name="uq_delegation_substitute",
        ),
        Index(
            "uq_delegation_substitute_gremiumwide",
            "gremium_id",
            "substitute_principal_id",
            unique=True,
            postgresql_where=text("member_principal_id IS NULL"),
        ),
        Index("ix_delegation_substitute_gremium", "gremium_id"),
    )
