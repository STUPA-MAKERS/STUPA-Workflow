"""Wire models of the ticket module (camelCase JSON).

Every model is frozen except ``NoteCreate`` and ``ReporterNoteCreate``, because their
base ``MessageFilesIn`` is mutable and a frozen class cannot derive from a mutable one.
Requests forbid extra fields. ``TicketCreate`` caps every string, because the route
is public. The context fields are optional and capped one by one.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from pydantic import ConfigDict, EmailStr, Field, JsonValue, field_validator

from app.modules.auth.people import PersonRef
from app.modules.files.schemas import AttachmentOut, MessageAttachmentOut, MessageFilesIn
from app.settings import get_settings
from app.shared.altcha import AltchaSolutionStr
from app.shared.i18n import Lang
from app.shared.mentions import MAX_MENTIONS
from app.shared.schemas import FrozenCamelModel, FrozenStrictCamelModel

TicketKind = Literal["bug", "question", "idea", "barrier"]
TicketStatus = Literal["new", "in_progress", "waiting", "done", "rejected"]
TicketSource = Literal["help", "mail", "team"]
TicketEventKind = Literal[
    "created", "status", "assignee", "kind", "todo_done", "category", "area", "mail_auto"
]
NoteVisibility = Literal["internal", "public"]

#: The most draft attachments one report binds.
MAX_TICKET_ATTACHMENTS = 5


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


class TicketContext(FrozenStrictCamelModel, frozen=True):
    """The technical context of a report. Every field is optional.

    ``url`` keeps a platform page only (``platform_page_url``); any other value is
    dropped, so the report still goes through.
    """

    url: str | None = Field(default=None, max_length=2048)
    route: str | None = Field(default=None, max_length=512)
    app_version: str | None = Field(default=None, alias="appVersion", max_length=64)
    user_agent: str | None = Field(default=None, alias="userAgent", max_length=512)
    viewport: str | None = Field(default=None, max_length=32)
    language: Lang | None = None
    color_scheme: Literal["light", "dark"] | None = Field(default=None, alias="colorScheme")

    @field_validator("url")
    @classmethod
    def _platform_url(cls, value: str | None) -> str | None:
        return platform_page_url(value)


class TicketCreate(FrozenStrictCamelModel, frozen=True):
    """A report. ``email`` and ``altcha`` are required without a session only.

    ``areaId`` names the Bereich; without it the report goes to ``Plattform``. A report
    to ``Plattform`` needs a ``kind``. A report to another Bereich needs a session and
    takes ``categoryId``, a Kategorie of that Bereich, in place of a kind.
    """

    kind: TicketKind | None = None
    area_id: UUID | None = Field(default=None, alias="areaId")
    category_id: UUID | None = Field(default=None, alias="categoryId")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    email: EmailStr | None = None
    context: TicketContext = Field(default_factory=TicketContext)
    attachment_ids: list[UUID] = Field(
        default_factory=list, alias="attachmentIds", max_length=MAX_TICKET_ATTACHMENTS
    )
    draft_token: str | None = Field(default=None, alias="draftToken", max_length=128)
    altcha: AltchaSolutionStr | None = None


class TicketCreated(FrozenCamelModel, frozen=True):
    """The only answer to a report: the ticket number (``T-7K3QX9MD``)."""

    number: str


class TicketReporter(FrozenCamelModel, frozen=True):
    """The reporter. ``email`` is the account e-mail or the given e-mail."""

    principal_id: UUID | None = Field(default=None, serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")
    email: str | None = None
    anonymized: bool = False


class TicketListItem(FrozenCamelModel, frozen=True):
    """A ticket row of the work list.

    ``kind`` is the fixed Kategorie of a ticket of the Bereich ``Plattform`` and null
    in every other Bereich. ``categoryId`` is the Kategorie of a ticket of another
    Bereich, else null.
    """

    id: UUID
    number: str
    area_id: UUID = Field(serialization_alias="areaId")
    kind: TicketKind | None = None
    category_id: UUID | None = Field(default=None, serialization_alias="categoryId")
    title: str
    status: TicketStatus
    source: TicketSource = "help"
    reporter: TicketReporter
    assignee: PersonRef | None = None
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class TicketAttachment(FrozenCamelModel, frozen=True):
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


class TicketEventOut(FrozenCamelModel, frozen=True):
    """An event of the ticket timeline."""

    id: UUID
    kind: TicketEventKind
    actor: PersonRef | None = None
    at: datetime
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)


class TicketNoteOut(FrozenCamelModel, frozen=True):
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
    mentions: tuple[PersonRef, ...] = Field(default_factory=tuple)


class TicketSkippedFile(FrozenCamelModel, frozen=True):
    """A file of a mail that did not become a file of the message.

    Attributes:
        reason: ``size`` for a file above the size limit, ``type`` for a file of a type
            that an upload refuses.
    """

    name: str
    size: int
    reason: Literal["size", "type"]


class TicketMailOut(FrozenCamelModel, frozen=True):
    """One mail of a ticket, for the team.

    Attributes:
        note_id: The message that the mail became; null for the first mail of the
            ticket and for an automatic mail.
        source: ``clean`` when the source can be downloaded, ``infected`` after a
            finding, ``closed`` without a scan result, ``gone`` after the anonymization.
    """

    id: UUID
    note_id: UUID | None = Field(default=None, serialization_alias="noteId")
    direction: Literal["in", "out"] = "in"
    from_name: str | None = Field(default=None, serialization_alias="fromName")
    from_address: str | None = Field(default=None, serialization_alias="fromAddress")
    cc: tuple[str, ...] = Field(default_factory=tuple)
    subject: str | None = None
    automatic: bool = False
    source: Literal["clean", "infected", "closed", "gone"] = "gone"
    source_size: int = Field(default=0, serialization_alias="sourceSize")
    skipped: tuple[TicketSkippedFile, ...] = Field(default_factory=tuple)
    at: datetime


class TicketRef(FrozenCamelModel, frozen=True):
    """A reference to another ticket by id and number."""

    id: UUID
    number: str


class ContextTarget(FrozenCamelModel, frozen=True):
    """The application or meeting of ``context.route``, when the viewer reads it."""

    kind: Literal["application", "meeting"]
    id: UUID
    title: str


class TicketDetail(TicketListItem, frozen=True):
    """A ticket with body, context, files, notes and events."""

    body: str
    context: Mapping[str, JsonValue] = Field(default_factory=dict)
    attachments: tuple[TicketAttachment, ...] = Field(default_factory=tuple)
    notes: tuple[TicketNoteOut, ...] = Field(default_factory=tuple)
    events: tuple[TicketEventOut, ...] = Field(default_factory=tuple)
    duplicate_of: TicketRef | None = Field(default=None, serialization_alias="duplicateOf")
    follow_up_of: TicketRef | None = Field(default=None, serialization_alias="followUpOf")
    context_target: ContextTarget | None = Field(default=None, serialization_alias="contextTarget")
    open_todo_count: int = Field(default=0, serialization_alias="openTodoCount")
    closed_at: datetime | None = Field(default=None, serialization_alias="closedAt")
    anonymized_at: datetime | None = Field(default=None, serialization_alias="anonymizedAt")
    sender_blocked: bool = Field(default=False, serialization_alias="senderBlocked")
    mails: tuple[TicketMailOut, ...] = Field(default_factory=tuple)


class TicketPatch(FrozenStrictCamelModel, frozen=True):
    """A change of status, assignee, Kategorie or Bereich. ``assigneeId: null`` unassigns.

    ``kind`` is the Kategorie of a ticket of ``Plattform``; ``categoryId`` is the
    Kategorie of a ticket of another Bereich, and ``null`` clears it. ``areaId`` moves
    the ticket to another Bereich.
    """

    status: TicketStatus | None = None
    assignee_id: UUID | None = Field(default=None, alias="assigneeId")
    kind: TicketKind | None = None
    category_id: UUID | None = Field(default=None, alias="categoryId")
    area_id: UUID | None = Field(default=None, alias="areaId")
    duplicate_of_id: UUID | None = Field(default=None, alias="duplicateOfId")
    complete_todos: bool | None = Field(default=None, alias="completeTodos")


class TicketManualCreate(FrozenStrictCamelModel, frozen=True):
    """A ticket that a person of the team writes by hand for an account or an address.

    Exactly one of ``reporterId`` (an account) and ``email`` names the person of the
    ticket. ``body`` is the note of the team and stays with the team. ``message`` is the
    first public message to the person. ``kind`` goes with ``Plattform`` and
    ``categoryId`` with every other Bereich.
    """

    area_id: UUID = Field(alias="areaId")
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=10000)
    kind: TicketKind | None = None
    category_id: UUID | None = Field(default=None, alias="categoryId")
    reporter_id: UUID | None = Field(default=None, alias="reporterId")
    email: EmailStr | None = None
    message: str = Field(default="", max_length=10000)


class TicketFollowUp(FrozenCamelModel, frozen=True):
    """The answer to a message that became a new ticket: the new ticket."""

    follow_up: TicketRef = Field(serialization_alias="followUp")


class NoteBody(FrozenStrictCamelModel, frozen=True):
    """The edit of a message of the reporter: the text only. It keeps the mentions."""

    body: str = Field(min_length=1, max_length=10000)


class NotePatch(NoteBody, frozen=True):
    """The edit of a team note: the text and, optionally, the mentions.

    ``mentions`` null keeps the stored mentions; a list replaces them, with the rules
    of ``NoteCreate``. Only a person that the list adds gets the mail.
    """

    mentions: list[UUID] | None = Field(default=None, max_length=MAX_MENTIONS)


class NoteCreate(MessageFilesIn):
    """A new note. The body may be empty only with at least one file.

    ``visibility`` defaults to ``internal``; ``public`` lets the reporter account read it.
    ``mentions`` holds the principal ids of mentioned holders of ``ticket.manage`` (at
    most 50, duplicates drop); another id gives 422 ``mention_not_member``.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    body: str = Field(max_length=10000)
    visibility: NoteVisibility = "internal"
    mentions: list[UUID] = Field(default_factory=list, max_length=MAX_MENTIONS)


class ReporterNoteCreate(MessageFilesIn):
    """A message of the reporter. It is always ``public`` and mentions nobody."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    body: str = Field(max_length=10000)


class ReporterTicketItem(FrozenCamelModel, frozen=True):
    """A ticket in the list of its reporter: no reporter, no assignee.

    ``kind`` is null for a ticket outside the Bereich ``Plattform``.
    """

    id: UUID
    number: str
    kind: TicketKind | None = None
    title: str
    status: TicketStatus
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ReporterTicketEvent(FrozenCamelModel, frozen=True):
    """A status change as the reporter sees it: no actor."""

    id: UUID
    kind: Literal["status"]
    at: datetime
    payload: Mapping[str, JsonValue] = Field(default_factory=dict)


class ReporterTicketDetail(ReporterTicketItem, frozen=True):
    """The own ticket of a reporter: the report, the public notes and the status changes.

    ``canReply`` is false while a sender block holds back the reporter.
    ``replyOpensNew`` is true when the ticket is closed for more than 14 days: a message
    then becomes a new ticket. ``body`` is empty for a ticket that the team wrote by
    hand, because that text is the note of the team.
    """

    body: str
    attachments: tuple[TicketAttachment, ...] = Field(default_factory=tuple)
    notes: list[TicketNoteOut] = Field(default_factory=list)
    events: tuple[ReporterTicketEvent, ...] = Field(default_factory=tuple)
    closed_at: datetime | None = Field(default=None, serialization_alias="closedAt")
    can_reply: bool = Field(default=True, serialization_alias="canReply")
    reply_opens_new: bool = Field(default=False, serialization_alias="replyOpensNew")


class TicketBlockedSender(FrozenCamelModel, frozen=True):
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


class TicketCounts(FrozenCamelModel, frozen=True):
    """Ticket counts per status."""

    new: int = 0
    in_progress: int = Field(default=0, serialization_alias="inProgress")
    waiting: int = 0
    done: int = 0
    rejected: int = 0


class TicketCategoryOut(FrozenCamelModel, frozen=True):
    """One Kategorie of a Bereich."""

    id: UUID
    name: str


class TicketAreaOut(FrozenCamelModel, frozen=True):
    """A Bereich with its Kategorien in their order.

    ``platform`` marks the built-in Bereich: it has no Gremium, its Kategorien are the
    four kinds of a report, and nobody deletes it. ``mine`` tells if the caller works
    in the Bereich. ``inApp`` tells if a signed-in person can choose the Bereich in the
    ticket dialog of the help menu; it is always true for ``Plattform``.
    """

    id: UUID
    name: str
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    platform: bool = False
    notify_new: bool = Field(default=True, serialization_alias="notifyNew")
    in_app: bool = Field(default=False, serialization_alias="inApp")
    categories: tuple[TicketCategoryOut, ...] = Field(default_factory=tuple)
    mine: bool = True


class TicketAreaChoice(FrozenCamelModel, frozen=True):
    """A Bereich that a signed-in person can choose in the ticket dialog."""

    id: UUID
    name: str
    platform: bool = False
    categories: tuple[TicketCategoryOut, ...] = Field(default_factory=tuple)


class TicketCategoryIn(FrozenStrictCamelModel, frozen=True):
    """A Kategorie in the save of a Bereich: ``id`` keeps a stored one, null adds one."""

    id: UUID | None = None
    name: str = Field(min_length=1, max_length=80)


class TicketAreaCreate(FrozenStrictCamelModel, frozen=True):
    """A new Bereich. It names at most one Gremium."""

    name: str = Field(min_length=1, max_length=80)
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    notify_new: bool = Field(default=True, alias="notifyNew")
    in_app: bool = Field(default=False, alias="inApp")
    categories: tuple[TicketCategoryIn, ...] = Field(default_factory=tuple, max_length=50)


class TicketAreaPatch(FrozenStrictCamelModel, frozen=True):
    """A change of a Bereich. A field that the body leaves out stays.

    ``categories`` is the whole ordered list: a stored Kategorie that the list leaves
    out is deleted, and its tickets lose their Kategorie.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    notify_new: bool | None = Field(default=None, alias="notifyNew")
    in_app: bool | None = Field(default=None, alias="inApp")
    categories: tuple[TicketCategoryIn, ...] | None = Field(default=None, max_length=50)
