"""Wire models of the ticket module (camelCase JSON).

Requests forbid extra fields. ``TicketCreate`` caps every string, because the route
is public. The context fields are optional and capped one by one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, JsonValue, field_validator

from app.modules.files.schemas import AttachmentOut, MessageAttachmentOut, MessageFilesIn
from app.settings import get_settings
from app.shared.altcha import AltchaSolutionStr
from app.shared.mentions import MAX_MENTIONS
from app.shared.people import PersonRef

TicketKind = Literal["bug", "question", "idea"]
TicketStatus = Literal["new", "in_progress", "done", "rejected"]
TicketEventKind = Literal["created", "status", "assignee", "kind", "todo_done"]
NoteVisibility = Literal["internal", "public"]

#: The most draft attachments one report binds.
MAX_TICKET_ATTACHMENTS = 5


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _CamelIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def _origin(url: str) -> tuple[str, str] | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return parts.scheme, parts.netloc.lower()


def platform_page_url(value: str | None) -> str | None:
    r"""Keep ``value`` only when it names a page of the platform, else ``None``.

    A page is an absolute http(s) URL on the origin of ``PUBLIC_BASE_URL``, or a path
    that starts with one ``/`` and resolves against ``PUBLIC_BASE_URL`` to that origin.
    The route is public and the ticket detail shows the url as a link, so a url to
    another host is dropped instead of being stored. A value with whitespace or a control
    character is dropped too, because a browser removes tab, CR and LF before it parses,
    so ``/\t/evil.example`` would become ``//evil.example`` and name another host.
    """
    if value is None or any(ord(ch) < 0x21 or ord(ch) == 0x7F for ch in value):
        return None
    base = get_settings().public_base_url
    platform = _origin(base)
    if value.startswith("/") and not value.startswith("//") and "\\" not in value:
        resolved = urljoin(base, value)
        return value if platform is not None and _origin(resolved) == platform else None
    origin = _origin(value)
    if origin is not None and origin == platform:
        return value
    return None


class TicketContext(_CamelIn):
    """The technical context of a report. Every field is optional.

    ``url`` keeps a platform page only (``platform_page_url``); any other value is
    dropped, so the report still goes through.
    """

    url: str | None = Field(default=None, max_length=2048)
    route: str | None = Field(default=None, max_length=512)
    app_version: str | None = Field(default=None, alias="appVersion", max_length=64)
    user_agent: str | None = Field(default=None, alias="userAgent", max_length=512)
    viewport: str | None = Field(default=None, max_length=32)
    language: Literal["de", "en"] | None = None
    color_scheme: Literal["light", "dark"] | None = Field(default=None, alias="colorScheme")

    @field_validator("url")
    @classmethod
    def _platform_url(cls, value: str | None) -> str | None:
        return platform_page_url(value)


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
    """A ticket row of the work list."""

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
    """A file of the ticket report."""

    id: UUID
    filename: str
    mime: str
    size: int
    scanned: bool

    @classmethod
    def of(cls, out: AttachmentOut) -> TicketAttachment:
        """Build the ticket form of an attachment."""
        return cls(
            id=out.id, filename=out.filename, mime=out.mime, size=out.size, scanned=out.scanned
        )


class TicketEventOut(_CamelModel):
    """An event of the ticket timeline."""

    id: UUID
    kind: TicketEventKind
    actor: PersonRef | None = None
    at: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TicketNoteOut(_CamelModel):
    """A note or message of a ticket.

    Attributes:
        mentions: The mentioned holders of ``ticket.manage`` in stored order. The view
            of the reporter (``/tickets/mine``) gets an empty list.
    """

    id: UUID
    author: PersonRef
    body: str
    at: datetime
    edited_at: datetime | None = Field(default=None, serialization_alias="editedAt")
    is_own: bool = Field(default=False, serialization_alias="isOwn")
    attachments: list[MessageAttachmentOut] = Field(default_factory=list)
    visibility: NoteVisibility = "internal"
    from_reporter: bool = Field(default=False, serialization_alias="fromReporter")
    mentions: list[PersonRef] = Field(default_factory=list)


class TicketRef(_CamelModel):
    """A reference to another ticket by id and number."""

    id: UUID
    number: str


class ContextTarget(_CamelModel):
    """The application or meeting of ``context.route``, when the viewer reads it."""

    kind: Literal["application", "meeting"]
    id: UUID
    title: str


class TicketDetail(TicketListItem):
    """A ticket with body, context, files, notes and events."""

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
    sender_blocked: bool = Field(default=False, serialization_alias="senderBlocked")


class TicketPatch(_CamelIn):
    """A change of status, assignee or kind. ``assigneeId: null`` unassigns."""

    status: TicketStatus | None = None
    assignee_id: UUID | None = Field(default=None, alias="assigneeId")
    kind: TicketKind | None = None
    duplicate_of_id: UUID | None = Field(default=None, alias="duplicateOfId")
    complete_todos: bool | None = Field(default=None, alias="completeTodos")


class NoteBody(_CamelIn):
    """The edit of a message of the reporter: the text only. It keeps the mentions."""

    body: str = Field(min_length=1, max_length=10000)


class NotePatch(NoteBody):
    """The edit of a team note: the text and, optionally, the mentions.

    ``mentions`` null keeps the stored mentions; a list replaces them, with the rules
    of ``NoteCreate``. Only a person that the list adds gets the mail.
    """

    mentions: list[UUID] | None = Field(default=None, max_length=MAX_MENTIONS)


class NoteCreate(MessageFilesIn, _CamelIn):
    """A new note. The body may be empty only with at least one file.

    ``visibility`` defaults to ``internal``; ``public`` lets the reporter account read it.
    ``mentions`` holds the principal ids of mentioned holders of ``ticket.manage`` (at
    most 50, duplicates drop); another id gives 422 ``mention_not_member``.
    """

    body: str = Field(max_length=10000)
    visibility: NoteVisibility = "internal"
    mentions: list[UUID] = Field(default_factory=list, max_length=MAX_MENTIONS)


class ReporterNoteCreate(MessageFilesIn, _CamelIn):
    """A message of the reporter. It is always ``public`` and mentions nobody."""

    body: str = Field(max_length=10000)


class ReporterTicketItem(_CamelModel):
    """A ticket in the list of its reporter: no reporter, no assignee."""

    id: UUID
    number: str
    kind: TicketKind
    title: str
    status: TicketStatus
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ReporterTicketEvent(_CamelModel):
    """A status change as the reporter sees it: no actor."""

    id: UUID
    kind: Literal["status"]
    at: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class ReporterTicketDetail(ReporterTicketItem):
    """The own ticket of a reporter: the report, the public notes and the status changes.

    ``canReply`` is false while a sender block holds back the reporter.
    """

    body: str
    attachments: list[TicketAttachment] = Field(default_factory=list)
    notes: list[TicketNoteOut] = Field(default_factory=list)
    events: list[ReporterTicketEvent] = Field(default_factory=list)
    closed_at: datetime | None = Field(default=None, serialization_alias="closedAt")
    can_reply: bool = Field(default=True, serialization_alias="canReply")


class TicketBlockedSender(_CamelModel):
    """One blocked sender. ``email`` is the stored address, or the account e-mail."""

    id: UUID
    kind: Literal["principal", "email"]
    person: PersonRef | None = None
    email: str | None = None
    blocked_by: PersonRef | None = Field(default=None, serialization_alias="blockedBy")
    blocked_at: datetime = Field(serialization_alias="blockedAt")
    source_ticket: TicketRef | None = Field(default=None, serialization_alias="sourceTicket")
    hit_count: int = Field(default=0, serialization_alias="hitCount")
    last_hit_at: datetime | None = Field(default=None, serialization_alias="lastHitAt")


class TicketCounts(_CamelModel):
    """Ticket counts per status."""

    new: int = 0
    in_progress: int = Field(default=0, serialization_alias="inProgress")
    done: int = 0
    rejected: int = 0
