"""Delegation DTOs (camelCase JSON).

A delegation is meeting-bound: created with ``meetingId`` + ``delegateId``; the
gremium and validity derive from the meeting. The substitute pool and the meeting
context have their own DTOs.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; populate-by-name."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Meeting delegation
# --------------------------------------------------------------------------- #
class DelegationCreate(_CamelModel):
    """Delegation for one meeting: ``delegateId`` gains access (and, with
    ``delegateVoting``, the vote) for meeting ``meetingId``."""

    meeting_id: UUID = Field(alias="meetingId")
    delegate_id: UUID = Field(alias="delegateId")
    delegate_voting: bool = Field(default=False, alias="delegateVoting")


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
    # Still revocable (meeting planned and not started)?
    revocable: bool
    # Direction from the caller's view: outgoing / incoming; None = uninvolved (admin).
    direction: str | None = None


# --------------------------------------------------------------------------- #
# Substitute pool
# --------------------------------------------------------------------------- #
class SubstituteCreate(_CamelModel):
    """Pool entry: ``substituteId`` may represent ``memberId`` (or any member when
    ``memberId`` is unset) in the gremium with no lead-time deadline."""

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


# --------------------------------------------------------------------------- #
# Meeting context (meeting detail dialog / dashboard card)
# --------------------------------------------------------------------------- #
class RecipientOut(_CamelModel):
    """Selectable delegation recipient (typeahead source)."""

    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    # Legitimized via the substitute pool: no lead-time deadline.
    via_pool: bool = Field(serialization_alias="viaPool")
    # Gremium member (otherwise: external recipient).
    is_member: bool = Field(serialization_alias="isMember")


class MeetingDelegationContext(_CamelModel):
    """Everything the frontend needs for the set-up-delegation dialog."""

    meeting_id: UUID = Field(serialization_alias="meetingId")
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    # Feature gates: gremium switch + global vote-delegation flag.
    allow_vote_delegation: bool = Field(serialization_alias="allowVoteDelegation")
    voting_delegation_enabled: bool = Field(
        serialization_alias="votingDelegationEnabled"
    )
    delegation_allow_external: bool = Field(
        serialization_alias="delegationAllowExternal"
    )
    # Deadline for non-pool delegations (UTC); None = status gate only (meeting has
    # no date). Pool delegations run until the meeting starts.
    deadline: datetime | None = None
    deadline_passed: bool = Field(serialization_alias="deadlinePassed")
    meeting_started: bool = Field(serialization_alias="meetingStarted")
    # May the caller delegate here at all (voting member)?
    can_delegate: bool = Field(serialization_alias="canDelegate")
    # Own outgoing delegation (at most one) + incoming ones.
    my_delegation: DelegationOut | None = Field(
        default=None, serialization_alias="myDelegation"
    )
    incoming: list[DelegationOut] = Field(default_factory=list)
    recipients: list[RecipientOut] = Field(default_factory=list)


class VoteDelegationStatus(_CamelModel):
    """Caller's delegation view of one vote (vote-cast banner)."""

    # Own vote for this ballot is delegated away: casting would 403.
    blocked: bool
    delegated_to_name: str | None = Field(
        default=None, serialization_alias="delegatedToName"
    )
    # The caller is exercising a delegated vote (badge "as substitute").
    exercising: bool
    delegated_by_name: str | None = Field(
        default=None, serialization_alias="delegatedByName"
    )
