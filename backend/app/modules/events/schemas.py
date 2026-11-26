"""API models of the Veranstaltungen (F/collaboration/events/003023)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.modules.events.rules import dates_problem
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Place = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Description = Annotated[str, StringConstraints(max_length=20000)]
ShopUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Participants = Annotated[int, Field(ge=0, le=1_000_000)]


class _Dates(FrozenStrictCamelModel, frozen=True):
    """The dates of an Event and their check (000736)."""

    starts_on: date | None = Field(default=None, alias="startsOn")
    start_time: time | None = Field(default=None, alias="startTime")
    ends_on: date | None = Field(default=None, alias="endsOn")
    end_time: time | None = Field(default=None, alias="endTime")

    @model_validator(mode="after")
    def _dates(self) -> Self:
        problem = dates_problem(self.starts_on, self.start_time, self.ends_on, self.end_time)
        if problem is not None:
            raise ValueError(f"{problem[0]}: the dates of the Event do not fit ({problem[1]})")
        return self


class EventCreate(_Dates, frozen=True):
    """The body of a new Event.

    Attributes:
        status: Empty for the start status of the list (F/administration/admin/003035).
    """

    team_id: UUID = Field(alias="teamId")
    title: Title
    status: str | None = Field(default=None, max_length=40)
    description_md: Description | None = Field(default=None, alias="descriptionMd")
    place: Place | None = None
    participants: Participants | None = None
    series_id: UUID | None = Field(default=None, alias="seriesId")
    shop_url: ShopUrl | None = Field(default=None, alias="shopUrl")


class EventUpdate(FrozenStrictCamelModel, frozen=True):
    """The body of a change. A field that the body leaves out stays as it is.

    The service checks the dates after it merged them with the stored ones.

    Attributes:
        version: The version that the person read.
    """

    version: int
    team_id: UUID | None = Field(default=None, alias="teamId")
    title: Title | None = None
    description_md: Description | None = Field(default=None, alias="descriptionMd")
    starts_on: date | None = Field(default=None, alias="startsOn")
    start_time: time | None = Field(default=None, alias="startTime")
    ends_on: date | None = Field(default=None, alias="endsOn")
    end_time: time | None = Field(default=None, alias="endTime")
    place: Place | None = None
    participants: Participants | None = None
    series_id: UUID | None = Field(default=None, alias="seriesId")
    shop_url: ShopUrl | None = Field(default=None, alias="shopUrl")


class EventStatusIn(FrozenStrictCamelModel, frozen=True):
    """The body of a status change."""

    status: str = Field(max_length=40)
    version: int


class EventTotalsOut(FrozenCamelModel, frozen=True):
    """The money of an Event as decimal strings with two places (000479)."""

    requested: str = "0.00"
    approved: str = "0.00"
    expenses: str = "0.00"
    income: str = "0.00"
    balance: str = "0.00"


class EventOut(FrozenCamelModel, frozen=True):
    """One Event as a member of its team sees it in the list.

    Attributes:
        team_name: The shown name of the team.
        series_name: The name of the series, else null.
        phase: The phase of the status (F/administration/admin/003036).
    """

    id: UUID
    number: str
    team_id: UUID = Field(alias="teamId")
    team_name: str | None = Field(default=None, alias="teamName")
    status: str
    phase: str
    title: str
    description_md: str | None = Field(default=None, alias="descriptionMd")
    starts_on: date | None = Field(default=None, alias="startsOn")
    start_time: time | None = Field(default=None, alias="startTime")
    ends_on: date | None = Field(default=None, alias="endsOn")
    end_time: time | None = Field(default=None, alias="endTime")
    place: str | None = None
    participants: int | None = None
    series_id: UUID | None = Field(default=None, alias="seriesId")
    series_name: str | None = Field(default=None, alias="seriesName")
    shop_url: str | None = Field(default=None, alias="shopUrl")
    totals: EventTotalsOut = Field(default_factory=EventTotalsOut)
    version: int
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class EventDecisionOut(FrozenCamelModel, frozen=True):
    """A decision of an Event: the valid decision of an Antrag or a closed vote (000482)."""

    kind: Literal["decision", "vote"]
    target_id: UUID | None = Field(default=None, alias="targetId")
    title: str
    decided_at: datetime | None = Field(default=None, alias="decidedAt")
    meeting_title: str | None = Field(default=None, alias="meetingTitle")
    result: str | None = None
    amount: str | None = None
    conditions: list[str] = Field(default_factory=list)


class EventEditionOut(FrozenCamelModel, frozen=True):
    """Another Event of the series that the viewer reads (000483)."""

    id: UUID
    number: str
    title: str
    status: str
    starts_on: date | None = Field(default=None, alias="startsOn")
    ends_on: date | None = Field(default=None, alias="endsOn")
    start_time: time | None = Field(default=None, alias="startTime")
    end_time: time | None = Field(default=None, alias="endTime")
    totals: EventTotalsOut = Field(default_factory=EventTotalsOut)


class EventDetailOut(EventOut, frozen=True):
    """One Event with its decisions and the other Events of its series (003029).

    Attributes:
        hidden_editions: The Events of the series that the viewer does not read.
    """

    decisions: tuple[EventDecisionOut, ...] = Field(default_factory=tuple)
    editions: tuple[EventEditionOut, ...] = Field(default_factory=tuple)
    hidden_editions: int = Field(default=0, alias="hiddenEditions")


class EventRefOut(FrozenCamelModel, frozen=True):
    """An Event that the caller writes: an option of the picker of a Buchung (003033)."""

    id: UUID
    number: str
    title: str
    team_name: str | None = Field(default=None, alias="teamName")
    starts_on: date | None = Field(default=None, alias="startsOn")
    ends_on: date | None = Field(default=None, alias="endsOn")
    start_time: time | None = Field(default=None, alias="startTime")
    end_time: time | None = Field(default=None, alias="endTime")


class EventTeamOut(FrozenCamelModel, frozen=True):
    """A team of the caller: an option of the field Team and of the chip Team."""

    id: UUID
    name: str


class SeriesOut(FrozenCamelModel, frozen=True):
    """A series of Events (``Reihe``, 000483)."""

    id: UUID
    name: str


class SeriesCreate(FrozenStrictCamelModel, frozen=True):
    """A new series."""

    name: str = Field(min_length=1, max_length=200)
