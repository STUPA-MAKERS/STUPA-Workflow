"""The read models of the meeting core: agenda items, attendance and keeper periods.

`livevote.schemas` holds the models of the live part and imports these.
"""

from __future__ import annotations

from datetime import datetime as _datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.shared.schemas import FrozenCamelModel


class KeeperPeriodOut(FrozenCamelModel, frozen=True):
    """One period of a protocol keeper.

    ``fromAt`` is ``None`` for the planned handover. ``toAt`` is ``None`` while the
    period runs. The positions are the 1-based numbers of the agenda items in the
    current agenda order. A position is ``None`` when the period has no item there
    or the item no longer exists; a reader then shows the time.
    """

    principal_id: UUID = Field(alias="principalId")
    name: str | None = None
    from_at: _datetime | None = Field(default=None, alias="fromAt")
    to_at: _datetime | None = Field(default=None, alias="toAt")
    from_agenda_item_id: UUID | None = Field(default=None, alias="fromAgendaItemId")
    to_agenda_item_id: UUID | None = Field(default=None, alias="toAgendaItemId")
    from_position: int | None = Field(default=None, alias="fromPosition")
    to_position: int | None = Field(default=None, alias="toPosition")


AttendanceStatus = Literal["present", "excused", "absent"]


#: A member reports only "present" or "excused" for the own record. Only the
#: meeting lead records "absent", that is absent without an excuse.
SelfAttendanceStatus = Literal["present", "excused"]


class AttendanceOut(FrozenCamelModel, frozen=True):
    """Attendance of a Gremium member for a meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    #: ``None`` means not yet recorded: a roster member without an entry.
    status: AttendanceStatus | None = None
    source: Literal["self", "lead"] | None = None
    #: The reason of an excuse. It is personal data: only the member and the
    #: meeting lead (``canWrite``) see it. All other readers get ``None``.
    note: str | None = None
    #: True when the requesting principal is this member, which allows self-marking.
    is_self: bool = Field(default=False, alias="isSelf")
    #: The member holds the gremium permission ``protocol.write`` and can keep
    #: the minutes. The keeper pickers offer only these members.
    can_keep_protocol: bool = Field(default=False, alias="canKeepProtocol")
    #: The member has an own vote now (gremium permission ``vote.cast``). Only such a
    #: member can delegate, so the lead offers "Vertretung eintragen" only for them.
    can_vote: bool = Field(default=False, alias="canVote")


class MeetingMemberOut(FrozenCamelModel, frozen=True):
    """Current Gremium member, as a protokollant candidate for a new meeting."""

    principal_id: UUID = Field(alias="principalId")
    display_name: str | None = Field(default=None, alias="displayName")
    email: str | None = None
    #: Only a member with the gremium permission ``protocol.write`` can keep the
    #: minutes. Another member gives 422 ``protokollant_needs_protocol_write``.
    can_keep_protocol: bool = Field(default=False, alias="canKeepProtocol")


class AgendaItemOut(FrozenCamelModel, frozen=True):
    """Agenda item: an assigned application or a free-text item."""

    id: UUID
    application_id: UUID | None = Field(default=None, alias="applicationId")
    #: The to-do card of an item of kind to-do (the item title is the card title).
    todo_id: UUID | None = Field(default=None, alias="todoId")
    #: The version of a Haushaltsplan that an item of kind plan decides.
    plan_version_id: UUID | None = Field(default=None, alias="planVersionId")
    #: The version of the plan is a draft: the item reads it and takes no vote.
    plan_reading: bool = Field(default=False, alias="planReading")
    #: The title of the item: its own title, else the title of its application.
    title: str | None = None
    #: The title of the application. None for a free-text item.
    application_title: str | None = Field(default=None, alias="applicationTitle")
    #: Markdown text of this agenda item.
    body: str | None = None
    position: int = 0
    #: The public protocol PDF redacts a non-public agenda item.
    non_public: bool = Field(default=False, alias="nonPublic")
    #: The time of the done mark ("TOP abhaken"). None for an item that is not done.
    done_at: _datetime | None = Field(default=None, alias="doneAt")
    #: Current application status as an i18n label.
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")
    #: The requested amount of the application (the decision proposal of the vote
    #: dialog starts with it). None for a free-text item.
    amount: Decimal | None = None


class AssignableApplicationOut(FrozenCamelModel, frozen=True):
    """Application of the meeting Gremium in a vote state, not yet on the agenda."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")
