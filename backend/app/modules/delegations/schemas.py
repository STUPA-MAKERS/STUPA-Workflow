"""Delegation DTOs with camelCase JSON.

A delegation is meeting-bound. The client creates it with `meetingId` and
`delegateId`. The gremium and the validity come from the meeting. The substitute
pool and the meeting context have their own DTOs.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """Base model with camelCase JSON aliases and populate-by-name."""

    model_config = ConfigDict(populate_by_name=True)


class DelegationCreate(_CamelModel):
    """Delegation for one meeting.

    `delegateId` gets access to the meeting `meetingId`. With `delegateVoting`
    the delegate also gets the vote.
    """

    meeting_id: UUID = Field(alias="meetingId")
    delegate_id: UUID = Field(alias="delegateId")
    delegate_voting: bool = Field(default=False, alias="delegateVoting")


class DelegationUpdate(_CamelModel):
    """Change the recipient or the vote transfer of an existing delegation.

    An omitted field stays unchanged. The meeting is fixed: a delegation for
    another meeting is a new delegation.
    """

    delegate_id: UUID | None = Field(default=None, alias="delegateId")
    delegate_voting: bool | None = Field(default=None, alias="delegateVoting")


class DelegationOut(_CamelModel):
    """Delegation view with resolved display names."""

    id: UUID
    meeting_id: UUID = Field(serialization_alias="meetingId")
    meeting_title: str | None = Field(default=None, serialization_alias="meetingTitle")
    meeting_date: str | None = Field(default=None, serialization_alias="meetingDate")
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    gremium_name: str | None = Field(default=None, serialization_alias="gremiumName")
    delegator_id: UUID = Field(serialization_alias="delegatorId")
    delegator_name: str | None = Field(default=None, serialization_alias="delegatorName")
    delegate_id: UUID = Field(serialization_alias="delegateId")
    delegate_name: str | None = Field(default=None, serialization_alias="delegateName")
    delegate_voting: bool = Field(serialization_alias="delegateVoting")
    via_pool: bool = Field(serialization_alias="viaPool")
    created_at: datetime = Field(serialization_alias="createdAt")
    # True while the meeting is planned and has not started.
    revocable: bool
    # Direction seen from the caller: outgoing or incoming. None means not involved (admin).
    direction: str | None = None


class SubstituteCreate(_CamelModel):
    """Pool entry that lets a substitute represent a member.

    `substituteId` may represent `memberId` in the gremium with no lead-time
    deadline. An unset `memberId` lets the substitute represent every member.
    """

    gremium_id: UUID = Field(alias="gremiumId")
    member_id: UUID | None = Field(default=None, alias="memberId")
    substitute_id: UUID = Field(alias="substituteId")


class SubstituteOut(_CamelModel):
    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    member_id: UUID | None = Field(default=None, serialization_alias="memberId")
    member_name: str | None = Field(default=None, serialization_alias="memberName")
    substitute_id: UUID = Field(serialization_alias="substituteId")
    substitute_name: str | None = Field(
        default=None, serialization_alias="substituteName"
    )


class RecipientOut(_CamelModel):
    """Delegation recipient that the typeahead can offer."""

    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    # True when the substitute pool legitimizes the recipient. No lead-time deadline.
    via_pool: bool = Field(serialization_alias="viaPool")
    # True for a gremium member. False marks an external recipient.
    is_member: bool = Field(serialization_alias="isMember")


class MeetingDelegationContext(_CamelModel):
    """Data that the frontend needs for the set-up-delegation dialog."""

    meeting_id: UUID = Field(serialization_alias="meetingId")
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    # Feature gates: the gremium switch and the global vote-delegation flag.
    allow_vote_delegation: bool = Field(serialization_alias="allowVoteDelegation")
    voting_delegation_enabled: bool = Field(
        serialization_alias="votingDelegationEnabled"
    )
    delegation_allow_external: bool = Field(
        serialization_alias="delegationAllowExternal"
    )
    # Deadline in UTC for a delegation from outside the pool. None means the meeting
    # has no date and only the status gate applies. A pool delegation runs until the
    # meeting starts.
    deadline: datetime | None = None
    deadline_passed: bool = Field(serialization_alias="deadlinePassed")
    meeting_started: bool = Field(serialization_alias="meetingStarted")
    # True when the caller is a voting member and may delegate here.
    can_delegate: bool = Field(serialization_alias="canDelegate")
    # The own outgoing delegation, at most one, and the incoming delegations.
    my_delegation: DelegationOut | None = Field(
        default=None, serialization_alias="myDelegation"
    )
    incoming: list[DelegationOut] = Field(default_factory=list)
    recipients: list[RecipientOut] = Field(default_factory=list)


class VoteDelegationStatus(_CamelModel):
    """Delegation view of one vote for the caller, shown in the vote-cast banner."""

    # The own vote for this ballot is delegated away. A cast would return 403.
    blocked: bool
    delegated_to_name: str | None = Field(
        default=None, serialization_alias="delegatedToName"
    )
    # True when the caller casts a delegated vote. The UI shows an "as substitute" badge.
    exercising: bool
    delegated_by_name: str | None = Field(
        default=None, serialization_alias="delegatedByName"
    )
