"""Delegation DTOs with camelCase JSON.

A delegation is meeting-bound. The client creates it with `meetingId` and
`delegateId`. The gremium and the validity come from the meeting. The substitute
pool, the faculty substitute groups (Z5) and the meeting context have their
own DTOs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.shared.i18n import I18nMap

# Limits of a faculty group name (Z5): one text per language.
_GROUP_NAME_MAX = 200
_GROUP_NAME_LANGS = frozenset({"de", "en"})
# Above this number of substitutes, the group view shows a warning (Z5). It is
# no hard limit.
SUBSTITUTE_WARN_ABOVE = 2


class _CamelModel(BaseModel):
    """Base model with camelCase JSON aliases and populate-by-name."""

    model_config = ConfigDict(populate_by_name=True)


class DelegationCreate(_CamelModel):
    """Delegation for one meeting.

    `delegateId` gets access to the meeting `meetingId`. With `delegateVoting`
    the delegate also gets the vote.

    Without `delegatorId` the caller delegates for themselves, only while the
    meeting is planned. With `delegatorId` the meeting lead (`can_manage`)
    enters a substitution for a missing member during a live meeting (O6). The
    delegate must then be a substitute of the faculty group of that member.
    """

    meeting_id: UUID = Field(alias="meetingId")
    delegate_id: UUID = Field(alias="delegateId")
    delegate_voting: bool = Field(default=False, alias="delegateVoting")
    delegator_id: UUID | None = Field(default=None, alias="delegatorId")


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
    # Name of the faculty group of the recipient (A8), or None without a group.
    # For a substitute, the group of the delegator wins.
    substitute_group_name: I18nMap | None = Field(
        default=None, serialization_alias="substituteGroupName"
    )


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


def _check_group_name(value: I18nMap) -> I18nMap:
    """Accept one name per supported language, at least one, none empty."""
    if not value:
        raise ValueError("at least one name required")
    unknown = set(value) - _GROUP_NAME_LANGS
    if unknown:
        raise ValueError(f"unsupported language: {', '.join(sorted(unknown))}")
    cleaned = {lang: text.strip() for lang, text in value.items()}
    if any(not text for text in cleaned.values()):
        raise ValueError("a name must not be empty")
    if any(len(text) > _GROUP_NAME_MAX for text in cleaned.values()):
        raise ValueError(f"a name has at most {_GROUP_NAME_MAX} characters")
    return cleaned


class SubstituteGroupCreate(_CamelModel):
    """New faculty group of a gremium (Z5)."""

    gremium_id: UUID = Field(alias="gremiumId")
    name_i18n: I18nMap = Field(alias="nameI18n")
    position: int = Field(default=0, ge=0, le=10_000)

    @field_validator("name_i18n")
    @classmethod
    def _name(cls, value: I18nMap) -> I18nMap:
        return _check_group_name(value)


class SubstituteGroupUpdate(_CamelModel):
    """Change the name or the position of a faculty group. Give at least one field."""

    name_i18n: I18nMap | None = Field(default=None, alias="nameI18n")
    position: int | None = Field(default=None, ge=0, le=10_000)

    @field_validator("name_i18n")
    @classmethod
    def _name(cls, value: I18nMap | None) -> I18nMap | None:
        return None if value is None else _check_group_name(value)

    @model_validator(mode="after")
    def _at_least_one(self) -> SubstituteGroupUpdate:
        if self.name_i18n is None and self.position is None:
            raise ValueError("at least one field required")
        return self


class SubstituteGroupMemberCreate(_CamelModel):
    """Add a person to a faculty group as a member or as a substitute."""

    principal_id: UUID = Field(alias="principalId")
    kind: Literal["member", "substitute"]


class SubstituteGroupMemberOut(_CamelModel):
    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    kind: Literal["member", "substitute"]
    # A member counts only while the gremium membership from the OIDC groups is
    # active. A substitute needs no membership and is always active.
    active: bool


class SubstituteGroupOut(_CamelModel):
    """Faculty group with its members and substitutes."""

    id: UUID
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    name_i18n: I18nMap = Field(serialization_alias="nameI18n")
    position: int
    members: list[SubstituteGroupMemberOut] = Field(default_factory=list)
    # True above two substitutes. The admin view shows a warning; it is no limit.
    too_many_substitutes: bool = Field(
        default=False, serialization_alias="tooManySubstitutes"
    )
