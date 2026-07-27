"""Meeting delegation tables.

`MeetingDelegation` holds a meeting-bound delegation. Each (meeting, delegator)
pair has exactly one outgoing delegation. The gremium of the row is the gremium
of the meeting. `delegate_voting` also transfers the voting right. The transfer
is exclusive and never a duplicate. The delegator cannot vote in that meeting.

`DelegationSubstitute` holds the substitute pool of one gremium. A member may
delegate to a pool member without the lead-time deadline. A pool member does not
have to be a gremium member. A NULL `member_principal_id` marks a substitute for
every member.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class MeetingDelegation(UUIDPkMixin, CreatedAtMixin, Base):
    """Delegation for a single meeting with an optional transfer of the voting right."""

    __tablename__ = "meeting_delegation"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    # Denormalized copy of the gremium of the meeting. It removes the join from
    # the hot voting-right check and from the "my delegations" queries.
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
    # True when the substitute pool legitimizes the delegation. Create then
    # applies no lead-time deadline.
    via_pool: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # The `sub` of the creator, either self-service or admin. It anchors the audit.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "delegator_principal_id", name="uq_meeting_delegation_delegator"
        ),
        # At most one takeover of the voting right per (meeting, delegate). A
        # principal casts exactly one ballot. A second voting delegation to the
        # same person would lapse without a message, because this is a transfer
        # and not a duplicate.
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
    """Pool entry that lets a substitute represent a member.

    The substitute acts without the lead-time deadline. A NULL
    `member_principal_id` lets the substitute represent every member.
    """

    __tablename__ = "delegation_substitute"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    # NULL marks a gremium-wide substitute that represents every member.
    member_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), nullable=True
    )
    substitute_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # A partial unique index deduplicates the gremium-wide entries, because
        # UniqueConstraint treats NULL values as distinct.
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
