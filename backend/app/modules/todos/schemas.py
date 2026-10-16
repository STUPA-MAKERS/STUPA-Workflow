"""Wire models of the todos module (camelCase JSON).

Responses serialize by alias. Requests forbid extra fields. A patch tells "not
sent" from ``null`` through ``model_fields_set``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.shared.people import PersonRef

TodoBoardKind = Literal["gremium", "personal", "team"]
TodoLabelColor = Literal["green", "blue", "violet", "amber", "red", "gray"]
TodoLinkKind = Literal["application", "meeting", "agenda_item", "ticket", "todo"]
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


class _Out(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class _In(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


# -- boards ---------------------------------------------------------------------


class TodoBoardSummary(_Out):
    id: UUID
    name: str
    kind: TodoBoardKind
    gremium_id: UUID | None = Field(default=None, serialization_alias="gremiumId")
    can_write: bool = Field(default=True, serialization_alias="canWrite")
    can_configure: bool = Field(default=False, serialization_alias="canConfigure")
    open_count: int = Field(default=0, serialization_alias="openCount")


class TodoColumnOut(_Out):
    id: UUID
    name: str
    position: int
    is_done: bool = Field(serialization_alias="isDone")
    card_count: int = Field(default=0, serialization_alias="cardCount")


class TodoLabelOut(_Out):
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


class TodoLinkOut(_Out):
    id: UUID
    kind: TodoLinkKind
    target_id: UUID = Field(serialization_alias="targetId")
    accessible: bool
    title: str | None = None
    url: str | None = None
    detail: TodoLinkDetail | None = None


class ChecklistCount(_Out):
    done: int = 0
    total: int = 0


class TodoCardTile(_Out):
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
    principal_id: UUID = Field(serialization_alias="principalId")
    display_name: str | None = Field(default=None, serialization_alias="displayName")


# -- card detail ------------------------------------------------------------------


class TodoCheckItemOut(_Out):
    id: UUID
    text: str
    done: bool
    position: int


class TodoEventOut(_Out):
    id: UUID
    kind: TodoEventKind
    actor: PersonRef | None = None
    at: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class TodoCommentOut(_Out):
    id: UUID
    author: PersonRef
    body: str
    mentions: list[PersonRef] = Field(default_factory=list)
    at: datetime
    edited_at: datetime | None = Field(default=None, serialization_alias="editedAt")
    is_own: bool = Field(default=False, serialization_alias="isOwn")


class TodoColumnRef(_Out):
    id: UUID
    name: str
    is_done: bool = Field(serialization_alias="isDone")


class TodoCardDetail(TodoCardTile):
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
    board_name: str = Field(serialization_alias="boardName")
    board_kind: TodoBoardKind = Field(serialization_alias="boardKind")
    column_name: str = Field(serialization_alias="columnName")
    labels: list[TodoLabelOut] = Field(default_factory=list)


class TodoMine(_Out):
    items: list[TodoMineItem] = Field(default_factory=list)
    due_soon_count: int = Field(default=0, serialization_alias="dueSoonCount")


class TodoLinkTarget(_Out):
    kind: TodoLinkKind
    target_id: UUID = Field(serialization_alias="targetId")
    title: str
    detail: TodoLinkDetail = Field(default_factory=TodoLinkDetail)


class TodoLinkedCard(_Out):
    id: UUID
    board_id: UUID = Field(serialization_alias="boardId")
    board_name: str = Field(serialization_alias="boardName")
    title: str
    column_name: str = Field(serialization_alias="columnName")
    is_done: bool = Field(serialization_alias="isDone")
    due_date: date | None = Field(default=None, serialization_alias="dueDate")
    assignees: list[PersonRef] = Field(default_factory=list)


# -- requests ---------------------------------------------------------------------


class BoardPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    archive_after_days: int | None = Field(default=None, alias="archiveAfterDays", ge=1, le=365)


class ColumnCreate(_In):
    name: str = Field(min_length=1, max_length=60)


class ColumnPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_done: Literal[True] | None = Field(default=None, alias="isDone")


class ColumnOrder(_In):
    column_ids: list[UUID] = Field(alias="columnIds", min_length=1, max_length=50)


class LabelCreate(_In):
    name: str = Field(min_length=1, max_length=40)
    color: TodoLabelColor


class LabelPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    color: TodoLabelColor | None = None


class LinkIn(_In):
    kind: TodoLinkKind
    target_id: UUID = Field(alias="targetId")


class CardCreate(_In):
    board_id: UUID = Field(alias="boardId")
    column_id: UUID | None = Field(default=None, alias="columnId")
    title: str = Field(min_length=1, max_length=300)
    description_md: str | None = Field(default=None, alias="descriptionMd", max_length=20000)
    due_date: date | None = Field(default=None, alias="dueDate")
    assignee_ids: list[UUID] = Field(default_factory=list, alias="assigneeIds", max_length=50)
    label_ids: list[UUID] = Field(default_factory=list, alias="labelIds", max_length=50)
    links: list[LinkIn] = Field(default_factory=list, max_length=20)


class CardPatch(_In):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description_md: str | None = Field(default=None, alias="descriptionMd", max_length=20000)
    due_date: date | None = Field(default=None, alias="dueDate")


class CardMove(_In):
    column_id: UUID = Field(alias="columnId")
    before_id: UUID | None = Field(default=None, alias="beforeId")
    after_id: UUID | None = Field(default=None, alias="afterId")


class AssigneeIn(_In):
    principal_id: UUID = Field(alias="principalId")


class CardLabelIn(_In):
    label_id: UUID = Field(alias="labelId")


class CheckItemCreate(_In):
    text: str = Field(min_length=1, max_length=500)


class CheckItemPatch(_In):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    done: bool | None = None
    position: int | None = Field(default=None, ge=0, le=1000)


class CommentIn(_In):
    body: str = Field(min_length=1, max_length=10000)
    mentions: list[UUID] = Field(default_factory=list, max_length=50)
