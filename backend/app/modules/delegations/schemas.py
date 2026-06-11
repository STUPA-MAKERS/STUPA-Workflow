"""Delegation-DTOs (#delegation-rework). camelCase im JSON (FE-Kontrakt).

Eine Delegation ist **sitzungsgebunden**: angelegt wird sie mit ``meetingId`` +
``delegateId``; Gremium und Gültigkeit ergeben sich aus der Sitzung. Der
Stellvertreter-Pool (``substitutes``) und der Sitzungs-Kontext (Deadline,
Empfänger-Optionen, eigener Status) haben eigene DTOs.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar."""

    model_config = ConfigDict(populate_by_name=True)


# --------------------------------------------------------------------------- #
# Sitzungs-Delegation
# --------------------------------------------------------------------------- #
class DelegationCreate(_CamelModel):
    """Vertretung für **eine** Sitzung: ``delegateId`` erhält Zugang (und mit
    ``delegateVoting`` das Stimmrecht) für die Sitzung ``meetingId``."""

    meeting_id: UUID = Field(alias="meetingId")
    delegate_id: UUID = Field(alias="delegateId")
    delegate_voting: bool = Field(default=False, alias="delegateVoting")


class DelegationOut(_CamelModel):
    """Delegations-Sicht inkl. aufgelöster Anzeige-Namen (FE braucht keine
    Principal-Lookups)."""

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
    # Widerruf noch möglich (Sitzung ``planned`` + vor Beginn)?
    revocable: bool
    # Richtung aus Sicht des Aufrufers: er delegiert (outgoing) / wird Vertreter
    # (incoming); None = unbeteiligt (Admin-Sicht).
    direction: str | None = None


# --------------------------------------------------------------------------- #
# Stellvertreter-Pool
# --------------------------------------------------------------------------- #
class SubstituteCreate(_CamelModel):
    """Pool-Eintrag: ``substituteId`` darf ``memberId`` (oder, ohne ``memberId``,
    jedes Mitglied) im Gremium ohne Vorlauf-Deadline vertreten."""

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
# Sitzungs-Kontext (Meeting-Detail-Dialog / Dashboard-Karte)
# --------------------------------------------------------------------------- #
class RecipientOut(_CamelModel):
    """Wählbarer Empfänger einer Delegation (Typeahead-Quelle)."""

    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    # Über den Stellvertreter-Pool legitimiert → keine Vorlauf-Deadline.
    via_pool: bool = Field(serialization_alias="viaPool")
    # Selbst Gremium-Mitglied (sonst: externer Empfänger).
    is_member: bool = Field(serialization_alias="isMember")


class MeetingDelegationContext(_CamelModel):
    """Alles, was das FE für den »Vertretung einrichten«-Dialog braucht."""

    meeting_id: UUID = Field(serialization_alias="meetingId")
    gremium_id: UUID = Field(serialization_alias="gremiumId")
    # Feature-Gates: Gremium-Schalter + globales Stimmrecht-Flag.
    allow_vote_delegation: bool = Field(serialization_alias="allowVoteDelegation")
    voting_delegation_enabled: bool = Field(
        serialization_alias="votingDelegationEnabled"
    )
    delegation_allow_external: bool = Field(
        serialization_alias="delegationAllowExternal"
    )
    # Deadline für Nicht-Pool-Delegationen (ISO, UTC); None = nur Status-Gate
    # (Sitzung ohne Termin). Pool-Delegationen gehen bis Sitzungsbeginn.
    deadline: datetime | None = None
    deadline_passed: bool = Field(serialization_alias="deadlinePassed")
    meeting_started: bool = Field(serialization_alias="meetingStarted")
    # Darf der Aufrufer hier überhaupt delegieren (stimmberechtigtes Mitglied)?
    can_delegate: bool = Field(serialization_alias="canDelegate")
    # Eigene ausgehende Delegation (max. eine) + an mich gerichtete.
    my_delegation: DelegationOut | None = Field(
        default=None, serialization_alias="myDelegation"
    )
    incoming: list[DelegationOut] = Field(default_factory=list)
    recipients: list[RecipientOut] = Field(default_factory=list)


class VoteDelegationStatus(_CamelModel):
    """Delegations-Sicht des Aufrufers auf **eine** Abstimmung (vote-cast-Banner)."""

    # Eigenes Stimmrecht für diese Abstimmung wegdelegiert → cast würde 403 liefern.
    blocked: bool
    delegated_to_name: str | None = Field(
        default=None, serialization_alias="delegatedToName"
    )
    # Der Aufrufer übt ein delegiertes Stimmrecht aus (Badge »in Vertretung«).
    exercising: bool
    delegated_by_name: str | None = Field(
        default=None, serialization_alias="delegatedByName"
    )
