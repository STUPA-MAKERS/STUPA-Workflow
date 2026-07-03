"""WebSocket message schemas for live voting.

Separate models for server→client (``meeting_state``, ``vote_opened``,
``vote_tally``, ``vote_closed``, ``error``) and client→server (``cast``,
``subscribe``). Every message is JSON ``{"type": …, …}`` with ``type`` as the
discriminator; the models are the single source of the WS contract.

Secrecy rules: ``vote_tally``/``vote_closed`` carry aggregates only — never
voter identities. While a secret vote is open, the live feed must not reveal
per-option counts: ``vote_tally`` then carries only participation (``cast`` of
``eligible``), ``counts`` is ``{}`` and ``leading`` is ``null``; full aggregates
arrive only with ``vote_closed`` (mirrors ``showBars = !secret || isClosed``).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.modules.voting.schemas import VoteOut


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fillable by field name (like the rest of the API)."""

    model_config = ConfigDict(populate_by_name=True)

    def dump(self) -> dict[str, object]:
        """JSON-ready dict (camelCase, enums/UUIDs as strings) for ``send_json``."""
        return self.model_dump(mode="json", by_alias=True)


class MeetingStateEvent(_CamelModel):
    """Current meeting state (beamer and voter)."""

    type: Literal["meeting_state"] = "meeting_state"
    active_application_id: UUID | None = Field(default=None, alias="activeApplicationId")
    status: Literal["planned", "live", "closed"]


class ViewersEvent(_CamelModel):
    """Who currently has the meeting page open — display names, deduplicated
    per user. Sent to the voter channel only (not the beamer)."""

    type: Literal["viewers"] = "viewers"
    viewers: list[str]


class VoteOpenedEvent(_CamelModel):
    """Vote opened — UI unlocks."""

    type: Literal["vote_opened"] = "vote_opened"
    vote_id: UUID = Field(alias="voteId")
    # None = generic motion (free-text agenda item), no application.
    application_id: UUID | None = Field(default=None, alias="applicationId")
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    # Motion text ("what is being voted on?") — for the live dialog/beamer.
    question: str | None = None
    options: list[str]
    closes_at: datetime | None = Field(default=None, alias="closesAt")
    # Secret vote → FE hides live bars (showBars = !secret || isClosed).
    secret: bool = False


class VoteTallyEvent(_CamelModel):
    """Live interim tally — aggregates only, never names.

    For an open secret vote ``counts`` stays empty and ``leading`` ``null``;
    only participation (``cast`` of ``eligible``) is visible. Construct via
    :meth:`from_vote` so this rule lives in one place.
    """

    type: Literal["vote_tally"] = "vote_tally"
    vote_id: UUID = Field(alias="voteId")
    # Votes per option — empty ``{}`` while the tally is concealed (see ``revealed``).
    counts: dict[str, int]
    # Ballots cast (participation). Always visible, even concealed: "N of M present".
    cast: int = 0
    eligible: int
    # Present members (reveal denominator) + whether choice counts are visible.
    present: int = 0
    revealed: bool = True
    quorum_met: bool = Field(alias="quorumMet")
    leading: str | None = None
    # Secret vote → FE hides live bars (showBars = !secret || isClosed).
    secret: bool = False

    @classmethod
    def from_vote(cls, vote: VoteOut) -> VoteTallyEvent:
        """Build the tally event from a vote.

        The reveal rule is already applied to ``tally`` in the service; here
        ``revealed`` is the safety gate: when ``False``, no choice counts or
        ``leading`` travel along (defensive, even if the service missed it)."""
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
    """Vote closed — final aggregated result."""

    type: Literal["vote_closed"] = "vote_closed"
    vote_id: UUID = Field(alias="voteId")
    result: Literal["passed", "rejected", "tie"]
    counts: dict[str, int]
    # Why the vote failed (only for ``rejected``): ``quorum`` or ``majority``
    # missed. ``None`` for ``passed``/``tie``.
    failed_reason: Literal["quorum", "majority"] | None = Field(
        default=None, alias="failedReason"
    )


class VoteCancelledEvent(_CamelModel):
    """Vote cancelled — no result, no branch fired."""

    type: Literal["vote_cancelled"] = "vote_cancelled"
    vote_id: UUID = Field(alias="voteId")


class ErrorEvent(_CamelModel):
    """WS error (e.g. ``not_eligible``, ``read_only``, ``not_open``)."""

    type: Literal["error"] = "error"
    code: str


class CastMessage(_CamelModel):
    """Ballot cast over the WS (server-side: group + unique + open + lock).

    ``asDelegation=true`` = proxy vote — own and delegated ballots are two
    separate casts."""

    type: Literal["cast"]
    vote_id: UUID = Field(alias="voteId")
    choice: str = Field(min_length=1)
    as_delegation: bool = Field(default=False, alias="asDelegation")


class SubscribeMessage(_CamelModel):
    """Request the initial/current state (reconnect consistency)."""

    type: Literal["subscribe"]
