"""Pure serialization of boards, cards, events and comments into the API schemas."""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import JsonValue

from app.modules.auth.people import DELETED_PERSON, PersonRef
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.todos import events as todo_events
from app.modules.todos.grouping import grouped
from app.modules.todos.links import HIDDEN, Resolved
from app.modules.todos.models import (
    TodoBoard,
    TodoCard,
    TodoCardEvent,
    TodoCheckItem,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoLabel,
)
from app.modules.todos.schemas import (
    ChecklistCount,
    EventIn,
    TodoAssignedBoard,
    TodoCardDetail,
    TodoCardTile,
    TodoCheckItemOut,
    TodoColumnOut,
    TodoColumnRef,
    TodoCommentOut,
    TodoEventBrief,
    TodoEventDecision,
    TodoEventEdition,
    TodoEventFacts,
    TodoEventOut,
    TodoEventTotals,
    TodoLabelOut,
    TodoLinkOut,
    TodoMineItem,
)
from app.modules.todos.service.common import CardLink, _Facts, _person, _ref_of, _uuid_of


def _event_brief(
    row: TodoCardEvent | None, series: Mapping[uuid.UUID, str]
) -> TodoEventBrief | None:
    if row is None:
        return None
    return TodoEventBrief(
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        start_time=row.start_time,
        end_time=row.end_time,
        place=row.place,
        participants=row.participants,
        series_id=row.series_id,
        series_name=series.get(row.series_id) if row.series_id is not None else None,
    )


def _totals_out(value: todo_events.Totals) -> TodoEventTotals:
    return TodoEventTotals(
        requested=todo_events.balance_text(value.requested),
        approved=todo_events.balance_text(value.approved),
        expenses=todo_events.balance_text(value.expenses),
        income=todo_events.balance_text(value.income),
        balance=todo_events.balance_text(value.balance),
    )


def _link_out(link: CardLink, resolved: Mapping[tuple[str, uuid.UUID], Resolved]) -> TodoLinkOut:
    target = resolved.get((link.kind, link.target_id), HIDDEN)
    return TodoLinkOut(
        id=link.id,
        kind=link.kind,  # pyright: ignore[reportArgumentType]
        target_id=link.target_id,
        accessible=target.accessible,
        title=target.title if target.accessible else None,
        url=target.url if target.accessible else None,
        detail=target.detail if target.accessible else None,
        granted=target.granted,
    )


def _label_out(label: TodoLabel) -> TodoLabelOut:
    return TodoLabelOut(id=label.id, name=label.name, color=label.color)  # pyright: ignore[reportArgumentType]


def _mine_item(
    tile: TodoCardTile, board: TodoBoard, column: TodoColumn, labels: Mapping[uuid.UUID, TodoLabel]
) -> TodoMineItem:
    """Build a card of ``GET /todos/mine`` from its tile, its board and its column."""
    return TodoMineItem(
        **tile.model_dump(by_alias=False),
        board_name=board.name,
        board_kind=board.kind,  # pyright: ignore[reportArgumentType]
        column_name=column.name,
        labels=[_label_out(labels[i]) for i in tile.label_ids if i in labels],
    )


def _assigned_board(
    board: TodoBoard,
    columns: Sequence[TodoColumn],
    labels: Iterable[TodoLabel],
    cards: Sequence[TodoCard],
    facts: _Facts,
    *,
    can_write: bool,
    gremium_id: uuid.UUID | None = None,
) -> TodoAssignedBoard:
    """Build a board row of ``mine_boards`` or ``all_boards`` from cards in board order."""
    return TodoAssignedBoard(
        id=board.id,
        name=board.name,
        kind=board.kind,  # pyright: ignore[reportArgumentType]
        team_id=board.team_id,
        gremium_id=gremium_id,
        can_write=can_write,
        columns=_column_outs(columns, Counter(c.column_id for c in cards)),
        labels=[_label_out(lab) for lab in labels],
        cards=[_tile(c, facts) for c in cards],
    )


def _column_outs(
    columns: Iterable[TodoColumn], per_column: Mapping[uuid.UUID, int]
) -> tuple[TodoColumnOut, ...]:
    """Build the columns of a board with the count of their cards."""
    return tuple(
        TodoColumnOut(
            id=c.id,
            name=c.name,
            position=c.position,
            is_done=c.is_done,
            card_count=per_column.get(c.id, 0),
        )
        for c in columns
    )


def _tile(card: TodoCard, facts: _Facts) -> TodoCardTile:
    """Build the tile of a card from the facts of its read."""
    done, total = facts.checklist.get(card.id, (0, 0))
    links = facts.links.get(card.id, ())
    assignees = sorted(
        (facts.people.get(pid, DELETED_PERSON) for pid in facts.assignees.get(card.id, ())),
        key=lambda p: ((p.display_name or "").casefold(), str(p.principal_id)),
    )
    return TodoCardTile(
        id=card.id,
        board_id=card.board_id,
        column_id=card.column_id,
        rank=card.rank,
        title=card.title,
        due_date=card.due_date,
        completed_at=card.completed_at,
        label_ids=sorted(facts.labels.get(card.id, ()), key=str),
        assignees=tuple(assignees),
        checklist=ChecklistCount(done=done, total=total),
        comment_count=facts.comments.get(card.id, 0),
        primary_link=_link_out(links[0], facts.resolved) if links else None,
        link_count=len(links),
        event=_event_brief(facts.events.get(card.id), facts.series),
        version=card.version,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _event_fields(payload: EventIn) -> dict[str, object]:
    """The columns of the event data of a card, from the request."""
    return {
        "starts_on": payload.starts_on,
        "ends_on": payload.ends_on,
        "start_time": payload.start_time,
        "end_time": payload.end_time,
        "place": _clean(payload.place),
        "participants": payload.participants,
        "series_id": payload.series_id,
    }


def _event_row(card_id: uuid.UUID, payload: EventIn) -> TodoCardEvent:
    return TodoCardEvent(card_id=card_id, **_event_fields(payload))


def _by_card[R: (TodoCheckItem, TodoEvent, TodoComment)](
    rows: Iterable[R],
) -> dict[uuid.UUID, tuple[R, ...]]:
    """Group rows by their card and keep the order of the query."""
    return grouped((row.card_id, row) for row in rows)


def _event_people(event: TodoEvent) -> tuple[uuid.UUID | None, ...]:
    """The actor of an event and, for an assignment, the assignee."""
    assigned = (_uuid_of(event.payload.get("principalId")),) if event.kind == "assigned" else ()
    return (event.actor_id, *assigned)


def _comment_people(comment: TodoComment) -> tuple[uuid.UUID | None, ...]:
    """The author of a comment and the people it mentions."""
    return (comment.author_id, *(_uuid_of(m) for m in comment.mentions or []))


def _detail_people(
    cards: Iterable[TodoCard],
    events: Mapping[uuid.UUID, Sequence[TodoEvent]],
    comments: Mapping[uuid.UUID, Sequence[TodoComment]],
) -> frozenset[uuid.UUID | None]:
    """The people that the whole cards name: creators, event people and comment people."""
    return frozenset(
        person
        for card in cards
        for person in (
            card.created_by,
            *(p for event in events.get(card.id, ()) for p in _event_people(event)),
            *(p for comment in comments.get(card.id, ()) for p in _comment_people(comment)),
        )
    )


def _detail_refs(
    cards: Iterable[TodoCard], facts: _Facts, events: Mapping[uuid.UUID, Sequence[TodoEvent]]
) -> frozenset[tuple[str, uuid.UUID]]:
    """The link targets that the whole cards name: their links and the (un)link events."""
    linked = (
        (link.kind, link.target_id) for card in cards for link in facts.links.get(card.id, ())
    )
    logged = (
        _ref_of(event.payload)
        for card in cards
        for event in events.get(card.id, ())
        if event.kind in ("linked", "unlinked")
    )
    return frozenset((*linked, *(ref for ref in logged if ref is not None)))


def _decision_out(decision: todo_events.Decision) -> TodoEventDecision:
    amount = decision.amount
    return TodoEventDecision(
        kind=decision.kind,  # pyright: ignore[reportArgumentType]
        target_id=decision.target_id,
        title=decision.title,
        decided_at=decision.decided_at,
        meeting_title=decision.meeting_title,
        result=decision.result,
        amount=todo_events.balance_text(amount) if amount is not None else None,
        conditions=decision.conditions,
    )


def _edition_out(
    other: TodoCard,
    board: TodoBoard,
    row: TodoCardEvent,
    sums: Mapping[uuid.UUID, todo_events.Totals],
) -> TodoEventEdition:
    return TodoEventEdition(
        id=other.id,
        board_id=board.id,
        board_name=board.name,
        title=other.title,
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        start_time=row.start_time,
        end_time=row.end_time,
        archived=other.archived_at is not None,
        totals=_totals_out(sums[other.id]),
    )


@dataclass(frozen=True, slots=True)
class _DetailParts:
    """What the whole cards of one read show, loaded before the first card is built."""

    facts: _Facts
    columns: Mapping[uuid.UUID, Sequence[TodoColumn]]
    board_labels: Mapping[uuid.UUID, Sequence[TodoLabel]]
    writable: Mapping[uuid.UUID, bool]
    items: Mapping[uuid.UUID, Sequence[TodoCheckItem]]
    events: Mapping[uuid.UUID, Sequence[TodoEvent]]
    comments: Mapping[uuid.UUID, Sequence[TodoComment]]
    resolved: Mapping[tuple[str, uuid.UUID], Resolved]
    persons: Mapping[uuid.UUID, PersonRef]
    me: uuid.UUID | None
    files: Mapping[uuid.UUID, list[MessageAttachmentOut]]
    gathered: Mapping[uuid.UUID, TodoEventFacts]

    def detail(self, card: TodoCard, board: TodoBoard) -> TodoCardDetail:
        """Build the whole card of ``card`` on ``board``."""
        tile = _tile(card, self.facts)
        own_labels = frozenset(tile.label_ids)
        labels = self.board_labels[board.id]
        return TodoCardDetail(
            **tile.model_dump(by_alias=False),
            description_md=card.description_md,
            board_name=board.name,
            board_kind=board.kind,  # pyright: ignore[reportArgumentType]
            can_write=self.writable[board.id],
            columns=tuple(
                TodoColumnRef(id=c.id, name=c.name, is_done=c.is_done)
                for c in self.columns[board.id]
            ),
            labels=tuple(_label_out(label) for label in labels if label.id in own_labels),
            board_labels=tuple(_label_out(label) for label in labels),
            created_by=self.persons.get(card.created_by, DELETED_PERSON),
            links=tuple(
                _link_out(link, self.resolved) for link in self.facts.links.get(card.id, ())
            ),
            checklist_items=tuple(
                TodoCheckItemOut(id=i.id, text=i.text, done=i.done, position=i.position)
                for i in self.items.get(card.id, ())
            ),
            events=tuple(
                _event_out(e, self.persons, self.resolved) for e in self.events.get(card.id, ())
            ),
            comments=tuple(
                _comment_out(c, self.persons, self.me, self.files.get(c.id, ()))
                for c in self.comments.get(card.id, ())
            ),
            archived_at=card.archived_at,
            event_facts=self.gathered.get(card.id),
        )


def _event_payload(
    event: TodoEvent,
    persons: Mapping[uuid.UUID, PersonRef],
    resolved: Mapping[tuple[str, uuid.UUID], Resolved],
) -> dict[str, JsonValue]:
    """The payload of an event as the timeline shows it.

    An assignment names the person instead of its id; a link or an unlink carries the
    title of the target when the viewer reads it.
    """
    payload: dict[str, JsonValue] = dict(event.payload or {})
    match event.kind:
        case "assigned":
            person = _person(persons, _uuid_of(payload.get("principalId")))
            return {
                "person": person.model_dump(by_alias=True, mode="json"),
                "added": bool(payload.get("added", False)),
            }
        case "linked" | "unlinked":
            ref = _ref_of(payload)
            target = resolved.get(ref, HIDDEN) if ref is not None else HIDDEN
            return {**payload, "title": target.title if target.accessible else None}
        case _:
            return payload


def _event_out(
    event: TodoEvent,
    persons: Mapping[uuid.UUID, PersonRef],
    resolved: Mapping[tuple[str, uuid.UUID], Resolved],
) -> TodoEventOut:
    return TodoEventOut(
        id=event.id,
        kind=event.kind,  # pyright: ignore[reportArgumentType]
        actor=_person(persons, event.actor_id) if event.actor_id is not None else None,
        at=event.created_at,
        payload=_event_payload(event, persons, resolved),
    )


def _comment_out(
    comment: TodoComment,
    persons: Mapping[uuid.UUID, PersonRef],
    me: uuid.UUID | None,
    attachments: Sequence[MessageAttachmentOut] = (),
) -> TodoCommentOut:
    return TodoCommentOut(
        id=comment.id,
        author=_person(persons, comment.author_id),
        body=comment.body,
        mentions=tuple(_person(persons, _uuid_of(m)) for m in comment.mentions or []),
        at=comment.created_at,
        edited_at=comment.edited_at,
        is_own=me is not None and comment.author_id == me,
        attachments=list(attachments),
    )
