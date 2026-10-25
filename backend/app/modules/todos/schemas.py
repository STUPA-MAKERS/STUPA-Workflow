"""Wire models of the todos module (camelCase JSON).

Responses serialize by alias. Requests forbid extra fields. A patch tells "not
sent" from ``null`` through ``model_fields_set``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.modules.files.schemas import MessageAttachmentOut, MessageFilesIn
from app.shared.people import PersonRef

TodoBoardKind = Literal["gremium", "personal", "team"]
TodoLabelColor = Literal["green", "blue", "violet", "amber", "red", "gray"]
TodoLinkKind = Literal[
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "gremium",
    "invoice",
    "expense",
    "ticket",
    "todo",
]
#: The kinds of a back-reference (``GET /todos/linked``): every kind but a card.
TodoLinkedKind = Literal[
    "application",
    "meeting",
    "agenda_item",
    "vote",
    "gremium",
    "invoice",
    "expense",
    "ticket",
]
TodoEventKind = Literal[
    "created",
    "moved",
    "assigned",
    "due",
    "linked",
    "unlinked",
    "checklist",
    "renamed",
    "archived",
    "restored",
]
TicketStatus = Literal["new", "in_progress", "done", "rejected"]
VoteStatus = Literal["draft", "open", "closed", "cancelled"]
VoteResult = Literal["passed", "rejected", "tie", "elected", "runoff"]
InvoiceStatus = Literal["open", "paid"]
BookingKind = Literal["expense", "income"]


class _Out(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _In(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TodoBoardSummary(_Out):
    """A board in the board list, with the rights of the caller and the open cards."""

    id: UUID
    name: str
    kind: TodoBoardKind
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    can_write: bool = Field(default=True, serialization_alias="canWrite")
    can_configure: bool = Field(default=False, serialization_alias="canConfigure")
    open_count: int = Field(default=0, serialization_alias="openCount")


class TodoColumnOut(_Out):
    """A column of a board."""

    id: UUID
    name: str
    position: int
    is_done: bool = Field(serialization_alias="isDone")
    card_count: int = Field(default=0, serialization_alias="cardCount")


class TodoLabelOut(_Out):
    """A label of a board."""

    id: UUID
    name: str
    color: TodoLabelColor


class TodoLinkDetail(_Out):
    """The extra facts of a link target; only the fields of its kind are set."""

    state_label: dict[str, str] | None = Field(default=None, serialization_alias="stateLabel")
    date: str | None = None
    meeting_title: str | None = Field(default=None, serialization_alias="meetingTitle")
    position: int | None = None
    number: str | None = None
    status: TicketStatus | None = None
    board_name: str | None = Field(default=None, serialization_alias="boardName")
    column_name: str | None = Field(default=None, serialization_alias="columnName")
    is_done: bool | None = Field(default=None, serialization_alias="isDone")
    amount: str | None = None
    counterparty: str | None = None
    cost_centre: str | None = Field(default=None, serialization_alias="costCentre")
    invoice_status: InvoiceStatus | None = Field(default=None, serialization_alias="invoiceStatus")
    booking_kind: BookingKind | None = Field(default=None, serialization_alias="bookingKind")
    vote_status: VoteStatus | None = Field(default=None, serialization_alias="voteStatus")
    vote_result: VoteResult | None = Field(default=None, serialization_alias="voteResult")


class TodoLinkOut(_Out):
    """A link of a card; ``accessible`` is false when the caller cannot read the target."""

    id: UUID
    kind: TodoLinkKind
    target_id: UUID = Field(serialization_alias="targetId")
    accessible: bool
    title: str | None = None
    url: str | None = None
    detail: TodoLinkDetail | None = None


class ChecklistCount(_Out):
    """Done and total items of a checklist."""

    done: int = 0
    total: int = 0


class TodoCardTile(_Out):
    """A card as a tile on the board."""

    id: UUID
    board_id: UUID = Field(serialization_alias="boardId")
    column_id: UUID = Field(serialization_alias="columnId")
    rank: str
    title: str
    due_date: date | None = Field(default=None, serialization_alias="dueDate")
    completed_at: datetime | None = Field(default=None, serialization_alias="completedAt")
    label_ids: list[UUID] = Field(default_factory=list, serialization_alias="labelIds")
    assignees: list[PersonRef] = Field(default_factory=list)
    checklist: ChecklistCount = Field(default_factory=ChecklistCount)
    comment_count: int = Field(default=0, serialization_alias="commentCount")
    primary_link: TodoLinkOut | None = Field(default=None, serialization_alias="primaryLink")
    link_count: int = Field(default=0, serialization_alias="linkCount")
    version: int = 1
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class TodoBoardOut(_Out):
    """A board with its columns, labels and live cards."""

    id: UUID
    name: str
    kind: TodoBoardKind
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    archive_after_days: int | None = Field(default=None, serialization_alias="archiveAfterDays")
    can_write: bool = Field(default=True, serialization_alias="canWrite")
    can_configure: bool = Field(default=False, serialization_alias="canConfigure")
    columns: list[TodoColumnOut] = Field(default_factory=list)
    labels: list[TodoLabelOut] = Field(default_factory=list)
    cards: list[TodoCardTile] = Field(default_factory=list)
    archived_count: int = Field(default=0, serialization_alias="archivedCount")


class TodoMember(_Out):
    """A member of a board."""

    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")


class TodoCheckItemOut(_Out):
    """A checklist item."""

    id: UUID
    text: str
    done: bool
    position: int


class TodoEventOut(_Out):
    """An event of the card history."""

    id: UUID
    kind: TodoEventKind
    actor: PersonRef | None = None
    at: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TodoCommentOut(_Out):
    """A comment of a card."""

    id: UUID
    author: PersonRef
    body: str
    mentions: list[PersonRef] = Field(default_factory=list)
    at: datetime
    edited_at: datetime | None = Field(default=None, serialization_alias="editedAt")
    is_own: bool = Field(default=False, serialization_alias="isOwn")
    attachments: list[MessageAttachmentOut] = Field(default_factory=list)


class TodoColumnRef(_Out):
    """A column of the board of a card."""

    id: UUID
    name: str
    is_done: bool = Field(serialization_alias="isDone")


class TodoCardDetail(TodoCardTile):
    """A card with its description, links, checklist, history and comments."""

    description_md: str | None = Field(default=None, serialization_alias="descriptionMd")
    board_name: str = Field(serialization_alias="boardName")
    board_kind: TodoBoardKind = Field(serialization_alias="boardKind")
    can_write: bool = Field(default=True, serialization_alias="canWrite")
    columns: list[TodoColumnRef] = Field(default_factory=list)
    labels: list[TodoLabelOut] = Field(default_factory=list)
    board_labels: list[TodoLabelOut] = Field(
        default_factory=list, serialization_alias="boardLabels"
    )
    created_by: PersonRef = Field(serialization_alias="createdBy")
    links: list[TodoLinkOut] = Field(default_factory=list)
    checklist_items: list[TodoCheckItemOut] = Field(
        default_factory=list, serialization_alias="checklistItems"
    )
    events: list[TodoEventOut] = Field(default_factory=list)
    comments: list[TodoCommentOut] = Field(default_factory=list)
    archived_at: datetime | None = Field(default=None, serialization_alias="archivedAt")


class TodoMineItem(TodoCardTile):
    """A card of ``GET /todos/mine``, with its board and column names."""

    board_name: str = Field(serialization_alias="boardName")
    board_kind: TodoBoardKind = Field(serialization_alias="boardKind")
    column_name: str = Field(serialization_alias="columnName")
    labels: list[TodoLabelOut] = Field(default_factory=list)


class TodoMine(_Out):
    """The cards assigned to the caller."""

    items: list[TodoMineItem] = Field(default_factory=list)
    due_soon_count: int = Field(default=0, serialization_alias="dueSoonCount")


class TodoAssignedBoard(_Out):
    """A board of ``GET /todos/mine/boards`` or ``GET /todos/all/boards``.

    ``columns`` are all columns of the board in their order; ``cardCount`` counts the
    live cards of ``cards`` in each. ``cards`` holds the live cards in board order, done
    ones included: under ``mine`` only the ones assigned to the caller, under ``all``
    every one. ``labels`` are the labels of the board.
    ``canWrite`` is the write right of the board (``BoardAccess.can_write``): false for
    a board that the caller only reads (``todo.read_all``).
    """

    id: UUID
    name: str
    kind: TodoBoardKind
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    can_write: bool = Field(default=True, serialization_alias="canWrite")
    columns: list[TodoColumnOut] = Field(default_factory=list)
    labels: list[TodoLabelOut] = Field(default_factory=list)
    cards: list[TodoCardTile] = Field(default_factory=list)


class TodoLinkTarget(_Out):
    """A target that a link can point at, found by the link search."""

    kind: TodoLinkKind
    target_id: UUID = Field(serialization_alias="targetId")
    title: str
    detail: TodoLinkDetail = Field(default_factory=TodoLinkDetail)


class TodoLinkedCard(_Out):
    """A card that links a given target."""

    id: UUID
    board_id: UUID = Field(serialization_alias="boardId")
    board_name: str = Field(serialization_alias="boardName")
    title: str
    column_name: str = Field(serialization_alias="columnName")
    is_done: bool = Field(serialization_alias="isDone")
    due_date: date | None = Field(default=None, serialization_alias="dueDate")
    assignees: list[PersonRef] = Field(default_factory=list)


class BoardPatch(_In):
    """A change of the board name or the archive delay."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    archive_after_days: int | None = Field(default=None, alias="archiveAfterDays", ge=1, le=365)


class ColumnCreate(_In):
    """A new column."""

    name: str = Field(min_length=1, max_length=60)


class ColumnPatch(_In):
    """A change of the column name, or ``isDone: true`` to make it the done column."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_done: Literal[True] | None = Field(default=None, alias="isDone")


class ColumnOrder(_In):
    """The new order of all columns."""

    column_ids: list[UUID] = Field(alias="columnIds", min_length=1, max_length=50)


class LabelCreate(_In):
    """A new label."""

    name: str = Field(min_length=1, max_length=40)
    color: TodoLabelColor


class LabelPatch(_In):
    """A change of a label."""

    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: TodoLabelColor | None = None


class LinkIn(_In):
    """A new link of a card."""

    kind: TodoLinkKind
    target_id: UUID = Field(alias="targetId")


class CardCreate(_In):
    """A new card."""

    board_id: UUID = Field(alias="boardId")
    column_id: UUID | None = Field(default=None, alias="columnId")
    title: str = Field(min_length=1, max_length=300)
    description_md: str | None = Field(default=None, alias="descriptionMd", max_length=20000)
    due_date: date | None = Field(default=None, alias="dueDate")
    assignee_ids: list[UUID] = Field(default_factory=list, alias="assigneeIds", max_length=50)
    label_ids: list[UUID] = Field(default_factory=list, alias="labelIds", max_length=50)
    links: list[LinkIn] = Field(default_factory=list, max_length=20)


class CardPatch(_In):
    """A change of the card fields; ``version`` guards against a lost update."""

    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description_md: str | None = Field(default=None, alias="descriptionMd", max_length=20000)
    due_date: date | None = Field(default=None, alias="dueDate")


class CardMove(_In):
    """A move inside the board, between ``afterId`` (above) and ``beforeId`` (below)."""

    column_id: UUID = Field(alias="columnId")
    before_id: UUID | None = Field(default=None, alias="beforeId")
    after_id: UUID | None = Field(default=None, alias="afterId")


class CardTransfer(_In):
    """The target of a transfer; ``beforeId``/``afterId`` as in ``CardMove`` (default: the end)."""

    board_id: UUID = Field(alias="boardId")
    column_id: UUID | None = Field(default=None, alias="columnId")
    before_id: UUID | None = Field(default=None, alias="beforeId")
    after_id: UUID | None = Field(default=None, alias="afterId")


class AssigneeIn(_In):
    """An assignee to add."""

    principal_id: UUID = Field(alias="principalId")


class CardLabelIn(_In):
    """A label to add to a card."""

    label_id: UUID = Field(alias="labelId")


class CheckItemCreate(_In):
    """A new checklist item."""

    text: str = Field(min_length=1, max_length=500)


class CheckItemPatch(_In):
    """A change of a checklist item."""

    text: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


class CommentIn(_In):
    """The edit of a comment: text and mentions; the files stay."""

    body: str = Field(min_length=1, max_length=10000)
    mentions: list[UUID] = Field(default_factory=list, max_length=50)


class CommentCreate(MessageFilesIn, _In):
    """A new comment. The body may be empty only with at least one file."""

    body: str = Field(max_length=10000)
    mentions: list[UUID] = Field(default_factory=list, max_length=50)
