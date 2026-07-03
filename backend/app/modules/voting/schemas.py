"""API schemas for the voting module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.shared.config_schemas import VoteConfig


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields also settable by name."""

    model_config = ConfigDict(populate_by_name=True)


class VoteCreate(_CamelModel):
    """``POST /applications/{id}/votes`` - create a vote (status ``draft``)."""

    config: VoteConfig
    eligible_group: str = Field(alias="eligibleGroup", min_length=1)
    # Resolution question, for the protocol.
    question: str | None = None
    # Authoritative eligible-voter count (roster basis), the denominator of the
    # percent quorum. NOT derived from logged-in users (that would be fail-open).
    # Required for a percent quorum; if missing there, the quorum is fail-closed.
    eligible_count: int | None = Field(default=None, alias="eligibleCount", ge=0)
    opens_state_id: UUID | None = Field(default=None, alias="opensStateId")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result_branch_transition_id: UUID | None = Field(
        default=None, alias="resultBranchTransitionId"
    )

    @model_validator(mode="after")
    def _percent_quorum_needs_eligible(self) -> VoteCreate:
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
    # Turnout progress (always visible, even secret/hidden): how many of the
    # present members have already voted.
    voted: int = 0
    present: int = 0
    # ``counts``/``leading`` are only visible when ``revealed`` - i.e. closed, or
    # (not secret and all present members have voted). Otherwise hidden.
    revealed: bool = True
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    result: Literal["passed", "rejected", "tie"] | None = None
    # Why the vote failed: ``quorum`` = quorum missed (fail-closed), ``majority`` =
    # quorum met but majority missed. None while open or on passed/tie.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


class VoteOut(_CamelModel):
    """Vote state + tally (``GET /votes/{id}``)."""

    id: UUID
    # None = generic resolution question (free-text TOP), no application.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # Meeting the vote hangs on (live vote); None for a pure async vote.
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    eligible_group: str = Field(alias="eligibleGroup")
    config: VoteConfig
    # ``cancelled``: the application left the vote state manually (vote aborted).
    status: Literal["draft", "open", "closed", "cancelled"]
    opens_at: datetime | None = Field(default=None, alias="opensAt")
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    result: Literal["passed", "rejected", "tie"] | None = None
    secret: bool
    tally: TallyOut


class BallotAccepted(_CamelModel):
    """Response for an accepted ballot."""

    status: Literal["cast", "changed"]


class VoteClosed(_CamelModel):
    """Result of closing (``POST /votes/{id}/close``)."""

    id: UUID
    meeting_id: UUID | None = Field(default=None, alias="meetingId")
    result: Literal["passed", "rejected", "tie"]
    tally: TallyOut
    fired_transition_id: UUID | None = Field(
        default=None, alias="firedTransitionId"
    )
    new_state_id: UUID | None = Field(default=None, alias="newStateId")
