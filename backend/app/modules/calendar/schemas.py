"""API schemas for the calendar module."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.shared.schemas import FrozenCamelModel, FrozenModel, FrozenStrictCamelModel

#: The answers of an invited person, in the order of the answer control.
AnswerKey = Literal["accept", "tentative", "decline"]
#: The kinds of entries of the Kalender. An Event is the kind ``event`` on the wire, and
#: the filter of the page counts it to the Termine.
EntryKind = Literal["meeting", "card", "event", "appointment", "external"]
#: The fetch intervals of an external calendar in minutes.
FetchInterval = Literal[15, 60, 360, 1440]

_MAX_TARGETS = 100


class CalendarFeedOut(FrozenModel, frozen=True):
    """Personal iCal subscription URL.

    The value is `None` until the principal generates a token.
    """

    url: str | None = None


class AppointmentIn(FrozenStrictCamelModel, frozen=True):
    """The whole data of a Termin, for the create and for the change.

    A Termin without ``startTime`` is all-day. The end must not be before the start, so
    a timed Termin on one day needs an end time after its start time.
    """

    title: str = Field(min_length=1, max_length=200)
    starts_on: date = Field(alias="startsOn")
    ends_on: date = Field(alias="endsOn")
    start_time: time | None = Field(default=None, alias="startTime")
    end_time: time | None = Field(default=None, alias="endTime")
    place: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    for_all: bool = Field(default=False, alias="forAll")
    gremium_ids: tuple[UUID, ...] = Field(default=(), alias="gremiumIds", max_length=_MAX_TARGETS)
    principal_ids: tuple[UUID, ...] = Field(
        default=(), alias="principalIds", max_length=_MAX_TARGETS
    )

    @model_validator(mode="after")
    def _span(self) -> Self:
        if not self.title.strip():
            raise ValueError("the title must not be blank")
        if self.ends_on < self.starts_on:
            raise ValueError("the end must not be before the start")
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("a timed Termin needs a start time and an end time")
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.ends_on == self.starts_on
            and self.end_time <= self.start_time
        ):
            raise ValueError("the end must be after the start")
        return self


class AnswerIn(FrozenStrictCamelModel, frozen=True):
    """The answer of the caller to a Termin."""

    answer: AnswerKey


class PersonOut(FrozenCamelModel, frozen=True):
    """A person by id and name. The Kalender never sends an e-mail address."""

    id: UUID
    name: str


class GremiumRefOut(FrozenCamelModel, frozen=True):
    """An invited Gremium by id and name."""

    id: UUID
    name: str


class AnswerOut(FrozenCamelModel, frozen=True):
    """The answer of one invited person."""

    principal_id: UUID = Field(serialization_alias="principalId")
    name: str
    answer: AnswerKey


class AppointmentOut(FrozenCamelModel, frozen=True):
    """A Termin as its reader sees it.

    ``answers`` is empty for a reader who is neither the creator nor invited, because
    only the creator and the invited persons see who comes. ``invited`` tells if the
    caller can answer, ``canEdit`` if the caller can change and delete the Termin.
    """

    id: UUID
    title: str
    starts_on: date = Field(serialization_alias="startsOn")
    ends_on: date = Field(serialization_alias="endsOn")
    start_time: time | None = Field(default=None, serialization_alias="startTime")
    end_time: time | None = Field(default=None, serialization_alias="endTime")
    place: str | None = None
    description: str | None = None
    for_all: bool = Field(default=False, serialization_alias="forAll")
    creator: PersonOut | None = None
    gremien: tuple[GremiumRefOut, ...] = ()
    persons: tuple[PersonOut, ...] = ()
    answers: tuple[AnswerOut, ...] = ()
    my_answer: AnswerKey | None = Field(default=None, serialization_alias="myAnswer")
    invited: bool = False
    can_edit: bool = Field(default=False, serialization_alias="canEdit")


class EntryOut(FrozenCamelModel, frozen=True):
    """One entry of the Kalender.

    ``id`` is the id of the meeting, the card, the Termin or the external entry.
    ``source`` is the name that the page shows below the title: the Gremium of a
    meeting, the board of a card or an Event, the first invited Gremium of a Termin and
    the name of an external calendar. ``gremiumIds`` feeds the
    Gremium filter. ``mine`` marks a card assigned to the caller and a Termin that the
    caller created or is invited to.
    """

    kind: EntryKind
    id: UUID
    title: str
    starts_on: date = Field(serialization_alias="startsOn")
    ends_on: date = Field(serialization_alias="endsOn")
    start_time: time | None = Field(default=None, serialization_alias="startTime")
    end_time: time | None = Field(default=None, serialization_alias="endTime")
    place: str | None = None
    source: str | None = None
    gremium_ids: tuple[UUID, ...] = Field(default=(), serialization_alias="gremiumIds")
    mine: bool = False
    my_answer: AnswerKey | None = Field(default=None, serialization_alias="myAnswer")


class EntriesOut(FrozenCamelModel, frozen=True):
    """The entries of a span of days or of a search."""

    items: tuple[EntryOut, ...] = ()


class ExternalCalendarIn(FrozenStrictCamelModel, frozen=True):
    """The data of an external calendar. Without ``gremiumId`` it is for all persons."""

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=9, max_length=2000)
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    interval_minutes: FetchInterval = Field(default=60, alias="intervalMinutes")

    @model_validator(mode="after")
    def _https(self) -> Self:
        if not self.name.strip():
            raise ValueError("the name must not be blank")
        if not self.url.startswith("https://") or any(c.isspace() for c in self.url):
            raise ValueError("the address must start with https://")
        return self


class ExternalCalendarOut(FrozenCamelModel, frozen=True):
    """An external calendar with the state of its newest fetch, for the admin page.

    ``lastError`` is the cause code of the newest failed fetch and None after a success.
    """

    id: UUID
    name: str
    url: str
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    gremium_name: str | None = Field(default=None, serialization_alias="gremiumName")
    interval_minutes: int = Field(serialization_alias="intervalMinutes")
    last_attempt_at: datetime | None = Field(default=None, serialization_alias="lastAttemptAt")
    last_success_at: datetime | None = Field(default=None, serialization_alias="lastSuccessAt")
    last_error: str | None = Field(default=None, serialization_alias="lastError")
    entry_count: int = Field(default=0, serialization_alias="entryCount")


class ExternalEntryOut(FrozenCamelModel, frozen=True):
    """An entry of an external calendar with the name of its calendar. Read-only."""

    id: UUID
    title: str
    starts_on: date = Field(serialization_alias="startsOn")
    ends_on: date = Field(serialization_alias="endsOn")
    start_time: time | None = Field(default=None, serialization_alias="startTime")
    end_time: time | None = Field(default=None, serialization_alias="endTime")
    place: str | None = None
    description: str | None = None
    calendar: str
