"""Wire schemas of the public guest routes of a meeting (#17).

A guest has no account. These models carry only what a guest may see: the head of
the meeting, the own state and, once admitted, the participant view of the public
agenda items. They never carry the name of another person, the attendance list, a
delegation, or the content of a non-public agenda item.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.livevote.schemas import GuestsMode, GuestStatus, MeetingStatus, clean_guest_name
from app.modules.voting.schemas import MyBallot
from app.shared.altcha import AltchaSolutionStr
from app.shared.config_schemas import Quorum


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class GuestJoinBody(_CamelModel):
    """``POST /public/meetings/join/{code}`` — ask to join with a name."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    display_name: str = Field(alias="displayName", max_length=400)
    # The ALTCHA solution (base64 JSON). The dependency checks it before the route.
    altcha: AltchaSolutionStr | None = None

    @model_validator(mode="after")
    def _clean(self) -> GuestJoinBody:
        self.display_name = clean_guest_name(self.display_name)
        return self


class GuestBallotBody(_CamelModel):
    """``POST /public/meetings/{code}/votes/{voteId}/ballot`` — the choice of a guest."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    choice: str = Field(min_length=1, max_length=100)


class PublicMeetingHead(_CamelModel):
    """The head of a public meeting: what the join page shows."""

    code: str
    title: str
    gremium_name: str | None = Field(default=None, alias="gremiumName")
    date: _date | None = None
    start_time: _time | None = Field(default=None, alias="startTime")
    status: MeetingStatus
    started_at: _datetime | None = Field(default=None, alias="startedAt")
    guests_mode: GuestsMode = Field(alias="guestsMode")


class GuestAgendaItem(_CamelModel):
    """One agenda item in the guest view.

    A non-public item keeps its title (decision 2026-10-06) but never its text.
    """

    id: UUID
    position: int
    title: str | None = None
    kind: Literal["application", "freetext"]
    non_public: bool = Field(alias="nonPublic")
    # The protocol excerpt (draft) of a public item. Always None for a non-public one.
    body: str | None = None


class GuestTally(_CamelModel):
    counts: dict[str, int]
    voted: int
    present: int
    revealed: bool
    leading: str | None = None
    present_members: int | None = Field(default=None, alias="presentMembers")
    present_guests: int | None = Field(default=None, alias="presentGuests")


class GuestVote(_CamelModel):
    """A vote of a public agenda item, as a guest sees it."""

    id: UUID
    agenda_item_id: UUID | None = Field(default=None, alias="agendaItemId")
    question: str | None = None
    options: list[str]
    status: Literal["open", "closed"]
    secret: bool
    majority_rule: Literal["simple", "absolute", "two_thirds"] = Field(alias="majorityRule")
    guests_vote: bool = Field(alias="guestsVote")
    quorum: Quorum | None = None
    opened_at: _datetime | None = Field(default=None, alias="openedAt")
    closed_at: _datetime | None = Field(default=None, alias="closedAt")
    result: Literal["passed", "rejected", "tie"] | None = None
    failed_reason: Literal["quorum", "majority"] | None = Field(default=None, alias="failedReason")
    tally: GuestTally
    my_ballot: MyBallot = Field(alias="myBallot")
    can_cast: bool = Field(default=False, alias="canCast")


class GuestView(_CamelModel):
    """The participant view of an admitted guest: public items, votes, counts."""

    current_agenda_item_id: UUID | None = Field(default=None, alias="currentAgendaItemId")
    present_members: int = Field(alias="presentMembers")
    admitted_guests: int = Field(alias="admittedGuests")
    agenda: list[GuestAgendaItem]
    votes: list[GuestVote]


class GuestMe(_CamelModel):
    """The own state of a guest (``GET /public/meetings/{code}/me``)."""

    guest_id: UUID = Field(alias="guestId")
    number: int
    display_name: str | None = Field(default=None, alias="displayName")
    status: GuestStatus
    # Seconds until a rejected or removed guest may ask again, else None.
    retry_after: int | None = Field(default=None, alias="retryAfter")
    meeting: PublicMeetingHead
    view: GuestView | None = None
