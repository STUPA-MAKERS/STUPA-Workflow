"""Meeting delegation tables.

`MeetingDelegation` holds a meeting-bound delegation. Each (meeting, delegator)
pair has exactly one outgoing delegation. The gremium of the row is the gremium
of the meeting. `delegate_voting` also transfers the voting right. The transfer
is exclusive and never a duplicate. The delegator cannot vote in that meeting.

`DelegationSubstitute` holds the substitute pool of one gremium. A member may
delegate to a pool member without the lead-time deadline. A pool member does not
have to be a gremium member. A NULL `member_principal_id` marks a substitute for
every member.

`SubstituteGroup` is a faculty group of one gremium (Z5). It holds members and
substitutes in `SubstituteGroupMember`. A substitute of a group may represent
every member of that group without the lead-time deadline. A member counts only
while the gremium membership from the OIDC groups is active.
"""

from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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


# Role of a person in a faculty group.
SubstituteGroupMemberKind = Literal["member", "substitute"]


class SubstituteGroup(UUIDPkMixin, CreatedAtMixin, Base):
    """Faculty group of one gremium: members and their substitutes (Z5).

    A substitute of the group may represent every member of the group. The
    unique pair `(id, gremium_id)` is the target of the composite foreign key of
    `SubstituteGroupMember`, so a member row always carries the gremium of its
    group.
    """

    __tablename__ = "substitute_group"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    name_i18n: Mapped[dict[str, str]] = mapped_column(JSONB, server_default="{}")
    # Sort order of the groups of one gremium in the admin view.
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("id", "gremium_id", name="uq_substitute_group_id_gremium"),
        Index("ix_substitute_group_gremium", "gremium_id"),
    )


class SubstituteGroupMember(CreatedAtMixin, Base):
    """One person in a faculty group, as a member or as a substitute (Z5).

    `gremium_id` is a copy of the gremium of the group. The composite foreign
    key on `(group_id, gremium_id)` keeps the copy correct and deletes the row
    with the group. The partial unique index puts a member into at most one
    group per gremium. A substitute may be in more than one group.

    The privacy erasure of a principal deletes the rows of the principal
    explicitly. The principal row stays, so the CASCADE on `principal_id` does
    not apply there.
    """

    __tablename__ = "substitute_group_member"

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    gremium_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "gremium_id"],
            ["substitute_group.id", "substitute_group.gremium_id"],
            ondelete="CASCADE",
            name="fk_substitute_group_member_group",
        ),
        CheckConstraint("kind IN ('member', 'substitute')", name="kind"),
        Index(
            "uq_substitute_group_member_gremium_member",
            "gremium_id",
            "principal_id",
            unique=True,
            postgresql_where=text("kind = 'member'"),
        ),
        Index("ix_substitute_group_member_principal", "principal_id"),
    )
