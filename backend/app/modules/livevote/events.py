"""WebSocket message schemas for live voting.

The models from server to client are `meeting_state`, `vote_opened`,
`vote_tally`, `vote_closed` and `error`. The models from client to server are
`cast` and `subscribe`. Every message is JSON of the form `{"type": …, …}` with
`type` as the discriminator. These models are the single source of the
WebSocket contract.

Secrecy rules: `vote_tally` and `vote_closed` carry aggregates only. They never
carry voter identities. While a secret vote is open, the live feed must not
reveal the counts per option. `vote_tally` then carries the participation only,
which is `cast` of `eligible`. `counts` is `{}` and `leading` is `null`. The
full aggregates arrive with `vote_closed`. This mirrors
`showBars = !secret || isClosed`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.modules.voting.schemas import VoteOut


class _CamelModel(BaseModel):
    """Emit camelCase aliases in JSON and accept the field names too.

    The rest of the API uses the same convention.
    """

    model_config = ConfigDict(populate_by_name=True)

    def dump(self) -> dict[str, object]:
        """Return a JSON-ready dict for `send_json`.

        The keys are camelCase. Enums and UUIDs become strings.
        """
        return self.model_dump(mode="json", by_alias=True)


class MeetingStateEvent(_CamelModel):
    """Current meeting state (beamer and voter)."""

    type: Literal["meeting_state"] = "meeting_state"
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    status: Literal["planned", "live", "closed"]


class ViewersEvent(_CamelModel):
    """Who has the meeting page open now.

    The event carries display names, deduplicated per user. The server sends it
    to the voter channel only, never to the beamer.
    """

    type: Literal["viewers"] = "viewers"
    viewers: list[str]


class VoteOpenedEvent(_CamelModel):
    """A vote opened and the UI unlocks."""

    type: Literal["vote_opened"] = "vote_opened"
    vote_id: UUID = Field(alias="voteId")
    # `None` marks a generic motion: a free-text agenda item with no application.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    # Motion text for the live dialog and the beamer: what is the vote about?
    question: str | None = None
    options: list[str]
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    # A secret vote hides the live bars in the frontend (showBars = !secret || isClosed).
    secret: bool = False


class VoteTallyEvent(_CamelModel):
    """Live interim tally with aggregates only and never with names.

    For an open secret vote `counts` stays empty and `leading` stays `null`.
    Only the participation is visible, which is `cast` of `eligible`. Build the
    event with `from_vote`, so that this rule lives in one place.
    """

    type: Literal["vote_tally"] = "vote_tally"
    vote_id: UUID = Field(alias="voteId")
    # Votes per option. Stays empty while the tally is concealed, see `revealed`.
    counts: dict[str, int]
    # Ballots cast (participation). Always visible, even concealed: "N of M present".
    cast: int = 0
    eligible: int
    # Present members are the denominator of the reveal. `revealed` tells whether
    # the choice counts are visible.
    present: int = 0
    revealed: bool = True
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    # A secret vote hides the live bars in the frontend (showBars = !secret || isClosed).
    secret: bool = False

    @classmethod
    def from_vote(cls, vote: VoteOut) -> VoteTallyEvent:
        """Build the tally event from a vote.

        The service applies the reveal rule to `tally` already. Here `revealed`
        is the safety gate. On `False` no choice counts and no `leading` value
        travel with the event. This holds even when the service misses the rule.
        """
        revealed = vote.tally.revealed
        return cls(
            voteId=vote.id,
            counts=vote.tally.counts if revealed else {},
            cast=vote.tally.voted,
            eligible=vote.tally.eligible,
            present=vote.tally.present,
            revealed=revealed,
            quorumMet=vote.tally.quorum_met,
            leading=vote.tally.leading if revealed else None,
            secret=vote.secret,
        )


class VoteClosedEvent(_CamelModel):
    """A vote closed with the final aggregated result."""

    type: Literal["vote_closed"] = "vote_closed"
    vote_id: UUID = Field(alias="voteId")
    result: Literal["passed", "rejected", "tie"]
    counts: dict[str, int]
    # Why the vote failed. Set for `rejected` only, when the vote missed the
    # quorum or the majority. `None` for `passed` and for `tie`.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


class VoteCancelledEvent(_CamelModel):
    """A canceled vote has no result and fires no branch."""

    type: Literal["vote_cancelled"] = "vote_cancelled"
    vote_id: UUID = Field(alias="voteId")


class ErrorEvent(_CamelModel):
    """A WebSocket error, for example `not_eligible`, `read_only` or `not_open`."""

    type: Literal["error"] = "error"
    code: str


class CastMessage(_CamelModel):
    """A ballot cast over the WebSocket.

    The server checks the group, the unique constraint, the open state and the
    lock. `asDelegation=true` marks a proxy vote. The own ballot and the
    delegated ballot are two separate casts.
    """

    type: Literal["cast"]
    vote_id: UUID = Field(alias="voteId")
    choice: str = Field(min_length=1)
    as_delegation: bool = Field(default=False, alias="asDelegation")


class SubscribeMessage(_CamelModel):
    """Request the current state, which keeps a reconnect consistent."""

    type: Literal["subscribe"]
