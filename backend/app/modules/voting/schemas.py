"""API schemas for the voting module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.shared.config_schemas import Quorum, VoteConfig


class _CamelModel(BaseModel):
    """Give JSON the camelCase aliases. A field also accepts its Python name."""

    model_config = ConfigDict(populate_by_name=True)


class VoteCreate(_CamelModel):
    """``POST /applications/{id}/votes`` - create a vote (status ``draft``).

    ``eligibleGroup`` is the UUID of the gremium that votes. A free group key is not
    valid (422). The server sets the eligible-voter count from the roster of that
    gremium, so the body has no ``eligibleCount``. An unknown field gives 422.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    config: VoteConfig
    eligible_group: UUID = Field(alias="eligibleGroup")
    # The resolution question, for the protocol.
    question: str | None = None
    opens_state_id: UUID | None = Field(default=None, alias="opensStateId")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result_branch_transition_id: UUID | None = Field(
        default=None, alias="resultBranchTransitionId"
    )


class VoteCreateInternal(_CamelModel):
    """The server-side create payload with the eligible-voter count.

    ``VotingService.create`` builds it from ``VoteCreate`` and the roster of the
    gremium. The live-vote route builds it from the meeting. No client sends it.
    """

    config: VoteConfig
    eligible_group: UUID = Field(alias="eligibleGroup")
    question: str | None = None
    # Authoritative eligible-voter count (roster basis) and the denominator of the
    # percent quorum. It does NOT come from the logged-in users, because that would be
    # fail-open. A percent quorum requires it. Without it the quorum stays fail-closed.
    eligible_count: int | None = Field(default=None, alias="eligibleCount", ge=0)
    opens_state_id: UUID | None = Field(default=None, alias="opensStateId")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result_branch_transition_id: UUID | None = Field(
        default=None, alias="resultBranchTransitionId"
    )

    @model_validator(mode="after")
    def _percent_quorum_needs_eligible(self) -> VoteCreateInternal:
        """A percent quorum requires an eligible-voter count (fail-closed)."""
        quorum = self.config.quorum
        if quorum is not None and quorum.type == "percent" and self.eligible_count is None:
            raise ValueError(
                "eligibleCount is required when a percent quorum is configured"
            )
        return self


class BallotIn(_CamelModel):
    """``POST /votes/{id}/ballot`` - cast a vote (``choice`` in ``config.options``).

    ``asDelegation=true`` casts the represented vote: own and delegated voting
    rights are two separate ballots.
    """

    choice: str = Field(min_length=1)
    as_delegation: bool = Field(default=False, alias="asDelegation")


class TallyOut(_CamelModel):
    """Aggregated interim/final result. Only ``counts`` when ``secret``."""

    counts: dict[str, int]
    eligible: int
    # Turnout progress (always visible, even when secret or hidden): how many present
    # members have already voted.
    voted: int = 0
    present: int = 0
    # ``counts`` and ``leading`` are visible only when ``revealed``: the vote is closed,
    # or the vote is not secret and all present members have voted. Otherwise they stay
    # hidden.
    revealed: bool = True
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    result: Literal["passed", "rejected", "tie"] | None = None
    # Why the vote failed: ``quorum`` = quorum missed (fail-closed), ``majority`` =
    # quorum met but majority missed. It stays None while the vote is open, and on
    # passed or tie.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )
    # Attendance of a meeting vote (#17): the present members and the admitted guests.
    # An open vote shows the values of now, a closed vote the values fixed at the
    # close. None for a vote without a meeting and for a vote that closed before the
    # values were stored.
    present_members: int | None = Field(default=None, alias="presentMembers")
    present_guests: int | None = Field(default=None, alias="presentGuests")


class MyBallot(_CamelModel):
    """The own ballot of the calling principal in one vote.

    ``cast`` tells whether the principal has cast the own ballot. ``choice`` is the
    chosen option. A secret vote keeps the choice apart from the identity, so there
    ``choice`` is always None and only ``cast`` (from the voted marker) travels.
    """

    cast: bool = False
    choice: str | None = None


class VoteOut(_CamelModel):
    """Vote state + tally (``GET /votes/{id}``)."""

    id: UUID
    # A None value marks a generic resolution question of a free-text agenda item with
    # no application.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # The meeting that holds the vote (live vote). It is None for a pure async vote.
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    eligible_group: str = Field(alias="eligibleGroup")
    config: VoteConfig
    # ``cancelled``: the application left the vote state manually and aborted the vote.
    status: Literal["draft", "open", "closed", "cancelled"]
    opens_at: datetime | None = Field(default=None, alias="opensAt")
    # The planned end of the cast window (deadline). It is not the real close time.
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result: Literal["passed", "rejected", "tie"] | None = None
    secret: bool
    # Copies of ``config`` for the vote card, so a client needs no config parse.
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(
        default="simple", alias="majorityRule"
    )
    quorum: Quorum | None = None
    # The real moment when the vote opened (``open`` sets ``opens_at``).
    opened_at: datetime | None = Field(default=None, alias="openedAt")
    # The real moment when the vote ended (close or cancel). None while it runs.
    closed_at: datetime | None = Field(default=None, alias="closedAt")
    tally: TallyOut
    # A vote with guests (#17): no quorum, only the majority of the cast ballots. A
    # copy of ``config.guestsVote`` for the vote card.
    guests_vote: bool = Field(default=False, alias="guestsVote")
    # The own ballot of the caller. Only ``GET /votes/{id}`` sets it. Other responses
    # and the live-vote events leave it None.
    my_ballot: MyBallot | None = Field(default=None, alias="myBallot")
    # True when the caller holds a voting delegation for this vote and has cast the
    # represented ballot. Only ``GET /votes/{id}`` sets it.
    represented_cast: bool = Field(default=False, alias="representedCast")
    # What the calling principal may do with this vote. Only ``GET /votes/{id}`` sets
    # them. Every other response and the live-vote events leave them False.
    # ``canManage``: open, close, cancel and delete (``assert_can_manage``).
    # ``canCast``: cast an OWN ballot (roster of the gremium, human session). A
    # delegated ballot has its own check.
    can_manage: bool = Field(default=False, alias="canManage")
    can_cast: bool = Field(default=False, alias="canCast")


VoteStatus = Literal["draft", "open", "closed", "cancelled"]


class VoteListItem(_CamelModel):
    """One row of the vote list (``GET /votes``).

    The row carries no tally. The client reads the tally from ``GET /votes/{id}``.
    ``myBallot`` and ``canCast`` give the own ballot state of the caller: a secret vote
    gives only ``cast``, never the choice. ``meetingTitle`` and ``agendaPosition``
    (the 1-based number of the agenda item, "TOP 3") are None for a vote without a
    meeting. ``gremiumName`` is None when the vote names no gremium (an old row with a
    free group key).
    """

    id: UUID
    question: str | None = None
    status: VoteStatus
    result: Literal["passed", "rejected", "tie"] | None = None
    secret: bool
    application_id: UUID | None = Field(default=None, alias="applicationId")
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    meeting_title: str | None = Field(default=None, alias="meetingTitle")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    agenda_position: int | None = Field(default=None, alias="agendaPosition")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    created_at: datetime = Field(alias="createdAt")
    opened_at: datetime | None = Field(default=None, alias="openedAt")
    closed_at: datetime | None = Field(default=None, alias="closedAt")
    # The planned end of the cast window, not the real end.
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    can_cast: bool = Field(default=False, alias="canCast")
    my_ballot: MyBallot = Field(default_factory=MyBallot, alias="myBallot")


class BallotAccepted(_CamelModel):
    """Response for an accepted ballot.

    A ballot never changes after the cast (O11). A second cast gives 409
    ``already_voted``, so the only status is ``cast``.
    """

    status: Literal["cast"] = "cast"


class VoteClosed(_CamelModel):
    """Result of a vote close (``POST /votes/{id}/close``).

    The close always ends the vote. ``branchFired`` tells whether the pass or fail
    transition of the application also fired. It is False when the guard of that
    transition failed, when the current state has no such transition, or when the
    vote has no application (``applicationId`` is None). In the first two cases the
    audit log holds a ``vote_branch_blocked`` entry, and a person must move the
    application by hand.
    """

    id: UUID
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    application_id: UUID | None = Field(default=None, alias="applicationId")
    result: Literal["passed", "rejected", "tie"]
    tally: TallyOut
    closed_at: datetime | None = Field(default=None, alias="closedAt")
    fired_transition_id: UUID | None = Field(
        default=None, alias="firedTransitionId"
    )
    new_state_id: UUID | None = Field(default=None, alias="newStateId")
    branch_fired: bool = Field(default=False, alias="branchFired")
