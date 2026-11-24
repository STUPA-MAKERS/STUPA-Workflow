"""Card writes: create, change, move, transfer, complete, archive, links, agenda items."""

from __future__ import annotations

import uuid

from pydantic import JsonValue
from sqlalchemy import delete, func, select

from app.modules.audit.actions import AuditAction
from app.modules.auth.principal import Principal
from app.modules.todos import events as todo_events
from app.modules.todos import link_store
from app.modules.todos.link_audit import audit_link
from app.modules.todos.models import (
    Link,
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoCardEvent,
    TodoCardLabel,
    TodoCheckItem,
    TodoColumn,
    TodoLabel,
)
from app.modules.todos.schemas import (
    CardCreate,
    CardMove,
    CardPatch,
    CardTransfer,
    TodoCardDetail,
    TodoCardTile,
)
from app.modules.todos.service.common import _invalid, _iso_date, _now
from app.modules.todos.service.details import DetailOps
from app.modules.todos.service.ranks import (
    _append,
    _card_moved,
    _check_transfer_kinds,
    _pick_column,
    _place,
    _slot,
)
from app.modules.todos.service.rows import _event_row
from app.shared.errors import ConflictError


class CardOps(DetailOps):
    """The life of a card."""

    async def create(self, payload: CardCreate, principal: Principal) -> TodoCardDetail:
        """Create a card at the end of its column (default: the first column).

        ``event`` makes the card an Event (spec 000478). ``checklist`` holds the open items
        of a duplicate (spec 000554).

        Raises:
            NotFoundError: The board is unknown or not readable (HTTP 404).
            ValidationProblem: ``column_not_on_board``, ``assignee_not_allowed``,
                ``label_not_on_board``, ``link_target_not_found`` or an event error of
                ``_check_event`` (HTTP 422).
            ConflictError: ``event_link_taken`` (HTTP 409).
        """
        actor = await self._actor(principal)
        board = await self._board(payload.board_id, principal, write=True)
        await self._lock_board(board.id)
        columns = await self._columns(board.id)
        column = _pick_column(columns, payload.column_id)
        assignees = list(dict.fromkeys(payload.assignee_ids))
        await self._check_assignees(board, assignees)
        label_ids = list(dict.fromkeys(payload.label_ids))
        if label_ids and not set(label_ids) <= {label.id for label in await self._labels(board.id)}:
            raise _invalid("A label is not on this board.", "label_not_on_board", "labelIds")
        links = list(dict.fromkeys((link.kind, link.target_id) for link in payload.links))
        await self.links.prepare(links, principal)
        for kind, target_id in links:
            if not await self.links.readable(kind, target_id, principal):
                raise _invalid("The link target was not found.", "link_target_not_found", "links")
        if payload.event is not None:
            await self._check_event(board, payload.event)
            await todo_events.check_one_event(self.session, uuid.uuid4(), links)
        live = await self._column_cards(column.id)
        now = _now()
        card = TodoCard(
            id=uuid.uuid4(),
            board_id=board.id,
            column_id=column.id,
            rank="",
            title=payload.title.strip() or payload.title,
            description_md=payload.description_md,
            due_date=payload.due_date,
            created_by=actor,
            completed_at=now if column.is_done else None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        _append(live, [card])
        self.session.add(card)
        await self.session.flush()
        for principal_id in assignees:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=principal_id))
        for label_id in label_ids:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
        for kind, target_id in links:
            link = Link.between(("todo", card.id), (kind, target_id), actor, now)
            self.session.add(link)
            await audit_link(self.session, AuditAction.LINK_ADD, link, principal)
        for position, text in enumerate(payload.checklist):
            self.session.add(
                TodoCheckItem(
                    id=uuid.uuid4(),
                    card_id=card.id,
                    text=text.strip() or text,
                    done=False,
                    position=position,
                )
            )
        if payload.event is not None:
            self.session.add(_event_row(card.id, payload.event))
        self._event(card, "created", actor)
        await self.session.flush()
        if column.is_done:
            await self._write_ticket_done(card, board, actor)
        self._touch(board, card)
        await self.session.commit()
        self._mail("assigned", card, assignees, actor)
        return await self._detail(card, board, principal)

    async def patch(
        self, card_id: uuid.UUID, payload: CardPatch, principal: Principal
    ) -> TodoCardDetail:
        """Change the title, the description or the due date (``version`` required).

        Raises:
            NotFoundError: The card is unknown or not readable (HTTP 404).
            ConflictError: ``version`` is not the current one (HTTP 409,
                ``card_version_conflict``).
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if payload.version != card.version:
            raise ConflictError(
                "The card was changed in the meantime.", code="card_version_conflict"
            )
        fields = payload.model_fields_set
        title = (
            (payload.title.strip() or payload.title) if payload.title is not None else card.title
        )
        renamed = title != card.title
        described = "description_md" in fields and payload.description_md != card.description_md
        redated = "due_date" in fields and payload.due_date != card.due_date
        if renamed:
            self._event(card, "renamed", actor, {"from": card.title, "to": title})
            card.title = title
        if described:
            card.description_md = payload.description_md
        if redated:
            self._event(
                card,
                "due",
                actor,
                {"from": _iso_date(card.due_date), "to": _iso_date(payload.due_date)},
            )
            card.due_date = payload.due_date
        if renamed or described or redated:
            card.version += 1
            card.updated_at = _now()
            self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def move(
        self, card_id: uuid.UUID, payload: CardMove, principal: Principal
    ) -> TodoCardTile:
        """Move a card into a column, between ``afterId`` (above) and ``beforeId`` (below).

        Without neighbors the card goes to the end of the column. A change of the
        column writes a ``moved`` event; the entry into the done column sets
        ``completed_at`` and writes ``todo_done`` to the linked tickets.

        Raises:
            NotFoundError: The card is unknown or not readable (HTTP 404).
            ConflictError: ``card_moved``: a parallel transfer moved the card to
                another board while the move waited for the board lock (HTTP 409).
            ValidationProblem: ``column_not_on_board``, or ``rank_neighbors_invalid``
                for a neighbor outside the column or two neighbors that are not
                adjacent (HTTP 422).

        After the lock the card is read again, because a parallel move of the same card
        can have held the lock, and the column change must work from the committed
        column. A reorder that ranks every card of the column touches the board, so the
        board reads again.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, write=True)
        await self._lock_board(board.id)
        await self.session.refresh(card)
        if card.board_id != board.id:
            raise _card_moved()
        columns = {c.id: c for c in await self._columns(board.id)}
        target = columns.get(payload.column_id)
        if target is None:
            raise _invalid("The column is not on this board.", "column_not_on_board", "columnId")
        siblings = await self._column_cards(target.id, exclude=card.id)
        respread = _place(siblings, _slot(siblings, payload.after_id, payload.before_id), card)
        source = columns.get(card.column_id)
        if target.id != card.column_id:
            self._event(
                card,
                "moved",
                actor,
                {
                    "fromColumnId": str(card.column_id),
                    "fromColumnName": source.name if source is not None else "",
                    "toColumnId": str(target.id),
                    "toColumnName": target.name,
                },
            )
            card.column_id = target.id
            if target.is_done:
                card.completed_at = _now()
                await self._write_ticket_done(card, board, actor)
            else:
                card.completed_at = None
        card.updated_at = _now()
        self._touch(board, card)
        if respread:
            self._touch(board)
        await self.session.commit()
        return (await self.tiles([card], principal))[0]

    async def transfer(
        self, card_id: uuid.UUID, payload: CardTransfer, principal: Principal
    ) -> TodoCardDetail:
        """Move a card into a column of another board (default: the first column).

        The card goes between ``afterId`` (above) and ``beforeId`` (below), the same
        neighbors as ``move``; without them it goes to the end of the column.

        Labels are per board: a label of the card stays when the target board has a
        label with the same name (case-insensitive), else it is dropped. The service
        never creates a label on the target, because that needs ``todo.configure``.
        Assignees who are not members of the target board are dropped, without a mail.
        Links, comments, the checklist and the events stay with the card. A card
        without an assignee that leaves the actor's personal board gets the actor as
        assignee when the actor is a member of the target (no mail), so it stays in
        "Meine To-Dos".

        A card of a shared board (gremium or team) never moves into a personal board
        (403 ``transfer_to_personal``), because its comments, files and links would
        then leave the reach of everyone else on the board.

        Both boards are locked in id order, so two transfers between the same two
        boards in opposite directions wait instead of deadlocking.

        Raises:
            NotFoundError: The card or the target board is unknown or not readable
                (HTTP 404).
            ForbiddenError: ``todo_write_required`` for a board that the caller reads
                but cannot write, ``transfer_to_personal`` from a shared board into a
                personal board (HTTP 403).
            ConflictError: ``card_moved`` (a parallel transfer moved the card) or
                ``card_archived`` (HTTP 409).
            ValidationProblem: ``transfer_same_board``, ``column_not_on_board``, or
                ``rank_neighbors_invalid`` for a neighbor outside the target column
                (HTTP 422).

        Every read comes before the first change of the card, because a read after it
        autoflushes the card, and an UPDATE without ``updated_at`` expires it.
        """
        actor = await self._actor(principal)
        card, source = await self._card(card_id, principal, write=True)
        if payload.board_id == source.id:
            raise _invalid(
                "The card is on this board already. Use move.", "transfer_same_board", "boardId"
            )
        target = await self._board(payload.board_id, principal, write=True)
        _check_transfer_kinds(source, target)
        for board_id in sorted((source.id, target.id)):
            await self._lock_board(board_id)
        await self.session.refresh(card)
        if card.board_id != source.id:
            raise _card_moved()
        if card.archived_at is not None:
            raise ConflictError("An archived card cannot move.", code="card_archived")
        columns = await self._columns(target.id)
        column = _pick_column(columns, payload.column_id)
        from_column = await self.session.get(TodoColumn, card.column_id)
        own_labels = list(
            (
                await self.session.scalars(
                    select(TodoLabel)
                    .join(TodoCardLabel, TodoCardLabel.label_id == TodoLabel.id)
                    .where(TodoCardLabel.card_id == card.id)
                    .order_by(func.lower(TodoLabel.name), TodoLabel.id)
                )
            ).all()
        )
        by_name = {label.name.lower(): label for label in await self._labels(target.id)}
        matched = {label.id: by_name.get(label.name.lower()) for label in own_labels}
        kept = list(dict.fromkeys(m.id for m in matched.values() if m is not None))
        dropped_labels: list[JsonValue] = [
            label.name for label in own_labels if matched[label.id] is None
        ]
        assignees = set(
            (
                await self.session.scalars(
                    select(TodoAssignee.principal_id).where(TodoAssignee.card_id == card.id)
                )
            ).all()
        )
        members = await self.access.member_ids(target)
        dropped_assignees = assignees - members
        claim = source.kind == "personal" and not assignees and actor in members
        live = await self._column_cards(column.id)
        index = _slot(live, payload.after_id, payload.before_id)
        await self.session.execute(delete(TodoCardLabel).where(TodoCardLabel.card_id == card.id))
        if dropped_assignees:
            await self.session.execute(
                delete(TodoAssignee).where(
                    TodoAssignee.card_id == card.id,
                    TodoAssignee.principal_id.in_(dropped_assignees),
                )
            )
        now = _now()
        card.updated_at = now
        for label_id in kept:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
        self._event(
            card,
            "moved",
            actor,
            {
                "fromColumnId": str(card.column_id),
                "fromColumnName": from_column.name if from_column is not None else "",
                "toColumnId": str(column.id),
                "toColumnName": column.name,
                "fromBoardId": str(source.id),
                "fromBoardName": source.name,
                "toBoardId": str(target.id),
                "toBoardName": target.name,
                "droppedLabels": dropped_labels,
                "droppedAssignees": len(dropped_assignees),
            },
        )
        if claim:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=actor))
            self._event(card, "assigned", actor, {"principalId": str(actor), "added": True})
        respread = _place(live, index, card)
        card.board_id = target.id
        card.column_id = column.id
        if not column.is_done:
            card.completed_at = None
        elif card.completed_at is None:
            card.completed_at = now
            await self._write_ticket_done(card, target, actor)
        self._touch(source, card, removed=True)
        self._touch(target, card)
        if respread:
            self._touch(target)
        await self.session.commit()
        return await self._detail(card, target, principal)

    async def complete(self, card: TodoCard, board: TodoBoard, actor: uuid.UUID) -> bool:
        """Move an open card to the end of the done column, without a commit.

        Returns:
            True when the card moved (False: no done column, done already, archived,
            or a parallel transfer moved it to another board).

        The board lock orders this rank against a parallel move or create, and the card
        is read again after the lock.
        """
        await self._lock_board(board.id)
        await self.session.refresh(card)
        if card.board_id != board.id:
            return False
        columns = await self._columns(board.id)
        done = next((c for c in columns if c.is_done), None)
        if done is None or card.column_id == done.id or card.archived_at is not None:
            return False
        source = next((c for c in columns if c.id == card.column_id), None)
        live = await self._column_cards(done.id, exclude=card.id)
        _append(live, [card])
        self._event(
            card,
            "moved",
            actor,
            {
                "fromColumnId": str(card.column_id),
                "fromColumnName": source.name if source is not None else "",
                "toColumnId": str(done.id),
                "toColumnName": done.name,
            },
        )
        card.column_id = done.id
        card.completed_at = _now()
        card.updated_at = _now()
        await self._write_ticket_done(card, board, actor)
        self._touch(board, card)
        await self.session.flush()
        return True

    async def archive_card(self, card_id: uuid.UUID, principal: Principal) -> None:
        """Archive a card (``DELETE``); a second call changes nothing."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if card.archived_at is None:
            card.archived_at = card.updated_at = _now()
            self._event(card, "archived", actor)
            self._touch(board, card, removed=True)
            await self.session.commit()

    async def restore_card(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Bring an archived card back into its column.

        A card in the done column gets a new ``completed_at``, else the archive cron
        archives it again at its next run.

        The column is read before the card changes, because a later read autoflushes the
        card. ``completed_at`` would then go in a second UPDATE without an explicit
        ``updated_at``, and its ``onupdate=now()`` expires the attribute.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if card.archived_at is not None:
            column = await self.session.get(TodoColumn, card.column_id)
            card.archived_at = None
            card.updated_at = _now()
            if column is not None and column.is_done:
                card.completed_at = card.updated_at
            self._event(card, "restored", actor)
            self._touch(board, card)
            await self.session.commit()
        return await self._detail(card, board, principal)

    async def card_end(
        self, card_id: uuid.UUID, principal: Principal, *, write: bool
    ) -> tuple[TodoCard, TodoBoard]:
        """The card of a link end, locked, for a link change (spec 001404).

        Raises:
            NotFoundError: The card is not readable (HTTP 404).
            ForbiddenError: ``write`` and the caller does not write the card (HTTP 403).
        """
        return await self._card(card_id, principal, lock=True, write=write)

    async def check_new_link(self, card: TodoCard, other: tuple[str, uuid.UUID]) -> None:
        """Refuse a link that would give the Antrag, Buchung or invoice a second Event.

        Raises:
            ConflictError: ``event_link_taken`` (HTTP 409).
        """
        if await self.session.get(TodoCardEvent, card.id) is not None:
            await todo_events.check_one_event(self.session, card.id, [other])

    def note_link(
        self,
        card: TodoCard,
        board: TodoBoard,
        other: tuple[str, uuid.UUID],
        actor: uuid.UUID,
        *,
        added: bool,
    ) -> None:
        """Write the card event of a link change and touch the board. No commit."""
        payload: dict[str, JsonValue] = {"linkKind": other[0], "targetId": str(other[1])}
        self._event(card, "linked" if added else "unlinked", actor, payload)
        self._touch(board, card)

    async def card_for_agenda(
        self, card_id: uuid.UUID, gremium_id: uuid.UUID, principal: Principal
    ) -> TodoCard:
        """Check a card for a new agenda item of a meeting of ``gremium_id``.

        The call locks the board of the card, then the card, before the agenda locks
        the meeting. A card create locks the board and then inserts a meeting link,
        which takes a key share on the meeting row, so every path takes the board
        first and the two cannot deadlock.

        Raises:
            NotFoundError: The card is unknown or not readable (HTTP 404).
            ValidationProblem: The card is archived (``todo_archived``) or not on the
                board of the gremium (``todo_wrong_board``) (HTTP 422).
        """
        card, board = await self._card(card_id, principal, lock=True, write=True)
        if card.archived_at is not None:
            raise _invalid("The card is archived.", "todo_archived", "todoId")
        if gremium_id not in await self.access.agenda_gremien(board):
            raise _invalid(
                "The card is not on a board of this gremium.", "todo_wrong_board", "todoId"
            )
        return card

    async def link_agenda_item(
        self, card: TodoCard, agenda_item_id: uuid.UUID, principal: Principal
    ) -> None:
        """Link the card to the agenda item when it is not linked yet. No commit."""
        actor = await self._actor(principal)
        ends = (("todo", card.id), ("agenda_item", agenda_item_id))
        if await link_store.link_between(self.session, *ends) is not None:
            return
        self.session.add(Link.between(*ends, actor))
        self._event(
            card, "linked", actor, {"linkKind": "agenda_item", "targetId": str(agenda_item_id)}
        )
        board = await self.session.get(TodoBoard, card.board_id)
        if board is not None:
            self._touch(board, card)
