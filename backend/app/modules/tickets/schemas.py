"""Wire models of the ticket module (camelCase JSON).

Requests forbid extra fields. ``TicketCreate`` caps every string, because the route
is public. The context fields are optional and capped one by one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue

from app.modules.files.schemas import AttachmentOut
from app.shared.altcha import AltchaSolutionStr
from app.shared.people import PersonRef

TicketKind = Literal["bug", "question", "idea"]
TicketStatus = Literal["new", "in_progress", "done", "rejected"]
TicketEventKind = Literal["created", "status", "assignee", "kind", "todo_done"]

#: The most draft attachments one report binds.
MAX_TICKET_ATTACHMENTS = 5


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _CamelIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TicketContext(_CamelIn):
    """The technical context of a report. Every field is optional."""

    url: str | None = Field(default=None, max_length=2048)
    route: str | None = Field(default=None, max_length=512)
    app_version: str | None = Field(default=None, alias="appVersion", max_length=64)
    user_agent: str | None = Field(default=None, alias="userAgent", max_length=512)
    viewport: str | None = Field(default=None, max_length=32)
    language: Literal["de", "en"] | None = None
    color_scheme: Literal["light", "dark"] | None = Field(default=None, alias="colorScheme")


class TicketCreate(_CamelIn):
    """A report. ``email`` and ``altcha`` are required without a session only."""

    kind: TicketKind
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    email: EmailStr | None = None
    context: TicketContext = Field(default_factory=TicketContext)
    attachment_ids: list[UUID] = Field(
        default_factory=list, alias="attachmentIds", max_length=MAX_TICKET_ATTACHMENTS
    )
    draft_token: str | None = Field(default=None, alias="draftToken", max_length=128)
    altcha: AltchaSolutionStr | None = None


class TicketCreated(_CamelModel):
    """The only answer to a report: the ticket number (``T-0042``)."""

    number: str


class TicketReporter(_CamelModel):
    """The reporter. ``email`` is the account e-mail or the given e-mail."""

    principal_id: UUID | None = Field(default=None, serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    email: str | None = None
    anonymized: bool = False


class TicketListItem(_CamelModel):
    id: UUID
    number: str
    kind: TicketKind
    title: str
    status: TicketStatus
    reporter: TicketReporter
    assignee: PersonRef | None = None
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class TicketAttachment(_CamelModel):
    id: UUID
    filename: str
    mime: str
    size: int
    scanned: bool

    @classmethod
    def of(cls, out: AttachmentOut) -> TicketAttachment:
        return cls(
            id=out.id, filename=out.filename, mime=out.mime, size=out.size, scanned=out.scanned
        )


class TicketEventOut(_CamelModel):
    id: UUID
    kind: TicketEventKind
    actor: PersonRef | None = None
    at: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TicketNoteOut(_CamelModel):
    id: UUID
    author: PersonRef
    body: str
    at: datetime
    edited_at: datetime | None = Field(default=None, serialization_alias="editedAt")
    is_own: bool = Field(default=False, serialization_alias="isOwn")


class TicketRef(_CamelModel):
    id: UUID
    number: str


class ContextTarget(_CamelModel):
    """The application or meeting of ``context.route``, when the viewer reads it."""

    kind: Literal["application", "meeting"]
    id: UUID
    title: str


class TicketDetail(TicketListItem):
    body: str
    context: dict[str, JsonValue] = Field(default_factory=dict)
    attachments: list[TicketAttachment] = Field(default_factory=list)
    notes: list[TicketNoteOut] = Field(default_factory=list)
    events: list[TicketEventOut] = Field(default_factory=list)
    duplicate_of: TicketRef | None = Field(default=None, serialization_alias="duplicateOf")
    context_target: ContextTarget | None = Field(default=None, serialization_alias="contextTarget")
    open_todo_count: int = Field(default=0, serialization_alias="openTodoCount")
    closed_at: datetime | None = Field(default=None, serialization_alias="closedAt")
    anonymized_at: datetime | None = Field(default=None, serialization_alias="anonymizedAt")


class TicketPatch(_CamelIn):
    """A change of status, assignee or kind. ``assigneeId: null`` unassigns."""

    status: TicketStatus | None = None
    assignee_id: UUID | None = Field(default=None, alias="assigneeId")
    kind: TicketKind | None = None
    duplicate_of_id: UUID | None = Field(default=None, alias="duplicateOfId")
    complete_todos: bool | None = Field(default=None, alias="completeTodos")


class NoteBody(_CamelIn):
    body: str = Field(min_length=1, max_length=10000)


class TicketCounts(_CamelModel):
    new: int = 0
    in_progress: int = Field(default=0, serialization_alias="inProgress")
    done: int = 0
    rejected: int = 0
