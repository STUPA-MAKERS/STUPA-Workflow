"""Meeting delegation tables.

`MeetingDelegation` holds a meeting-bound delegation. Each (meeting, delegator)
pair has exactly one outgoing delegation. The gremium of the row is the gremium
of the meeting. `delegate_voting` transfers the voting right. A new row always
sets it (§F/meetings/delegations/002900), and a false value is the history of an
older rule in a held meeting. The transfer is exclusive and never a duplicate.
The delegator cannot vote in that meeting.

The substitute pool of a gremium (`DelegationSubstitute`) is in `gremien.models`,
because the pool belongs to a gremium and gives its read scope
(§S/backend/python/000652).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class MeetingDelegation(UUIDPkMixin, CreatedAtMixin, Base):
    """Delegation for a single meeting that transfers the voting right.

    A delegate can hold several delegations in one meeting, up to the limit of the Gremium
    (``delegation_max_per_delegate``). One cast of the delegate writes one ballot for each
    delegator with a voting delegation.
    """

    __tablename__ = "meeting_delegation"

    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meeting.id", ondelete="CASCADE"))
    #: Denormalized copy of the gremium of the meeting. It removes the join from
    #: the hot voting-right check and from the "my delegations" queries.
    gremium_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gremium.id", ondelete="CASCADE"))
    delegator_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    delegate_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    delegate_voting: Mapped[bool] = mapped_column(Boolean, server_default="true")
    #: True when the substitute pool legitimizes the delegation. Create then
    #: applies no lead-time deadline.
    via_pool: Mapped[bool] = mapped_column(Boolean, server_default="false")
    #: The `sub` of the creator, either self-service or admin. It anchors the audit.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "meeting_id", "delegator_principal_id", name="uq_meeting_delegation_delegator"
        ),
        Index("ix_meeting_delegation_meeting", "meeting_id"),
        Index("ix_meeting_delegation_delegate", "delegate_principal_id"),
    )
