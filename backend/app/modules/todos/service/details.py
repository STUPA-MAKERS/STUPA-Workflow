"""The detail reads of a card: one card, several cards, the tile."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from app.modules.auth.people import person_refs
from app.modules.auth.principal import Principal
from app.modules.todos.models import (
    Link,
    TodoBoard,
    TodoCard,
    TodoCheckItem,
    TodoComment,
    TodoEvent,
)
from app.modules.todos.schemas import TodoCardDetail, TodoCardTile
from app.modules.todos.service.base import TodoServiceBase
from app.modules.todos.service.common import CardLink
from app.modules.todos.service.rows import (
    _by_card,
    _detail_people,
    _detail_refs,
    _DetailParts,
)
from app.shared.errors import NotFoundError


class DetailOps(TodoServiceBase):
    """Card detail reads that the card writes answer with."""

    async def card(self, card_id: uuid.UUID, principal: Principal) -> TodoCardDetail:
        """Return the whole card, archived ones too.

        Raises:
            NotFoundError: The card is unknown or its board not readable (HTTP 404).
        """
        card, board = await self._card(card_id, principal)
        return await self._detail(card, board, principal)

    async def _card_link(self, card: TodoCard, link_id: uuid.UUID) -> CardLink:
        """One link as ``card`` shows it (spec 001401).

        Raises:
            NotFoundError: The link has no end on the card (HTTP 404).
        """
        link = await self.session.get(Link, link_id)
        if link is None or not link.has_end(("todo", card.id)):
            raise NotFoundError(f"link {link_id} not found")
        kind, target_id = link.other(("todo", card.id))
        return CardLink(link.id, kind, target_id)

    async def cards(
        self, card_ids: Sequence[uuid.UUID], principal: Principal
    ) -> list[TodoCardDetail]:
        """Return the whole cards of ``card_ids`` in their order, archived ones too.

        The read-ahead of the board page reads many cards in one request. A card that
        is unknown or whose board the caller cannot read is left out, as the single
        read answers 404 for it. A repeated id gives one card.
        """
        ids = list(dict.fromkeys(card_ids))
        found = {
            card.id: card
            for card in (
                await self.session.scalars(select(TodoCard).where(TodoCard.id.in_(ids)))
            ).all()
        }
        boards = {
            board.id: board
            for board in (
                await self.session.scalars(
                    select(TodoBoard).where(TodoBoard.id.in_({c.board_id for c in found.values()}))
                )
            ).all()
        }
        known = [
            (found[card_id], boards[found[card_id].board_id]) for card_id in ids if card_id in found
        ]
        pairs = [
            (card, board) for card, board in known if await self.access.can_read(board, principal)
        ]
        return await self._details(pairs, principal)

    async def tile(self, card_id: uuid.UUID, principal: Principal) -> TodoCardTile:
        """Return the tile of a live card, the same one that the board read holds.

        A live ping names a card, and the page reads its tile here.

        Raises:
            NotFoundError: The card is unknown, archived or not readable (HTTP 404).
        """
        card, _board = await self._card(card_id, principal)
        if card.archived_at is not None:
            raise NotFoundError(f"card {card_id} not found")
        return (await self.tiles([card], principal))[0]

    async def _detail(
        self, card: TodoCard, board: TodoBoard, principal: Principal
    ) -> TodoCardDetail:
        return (await self._details([(card, board)], principal))[0]

    async def _details(
        self, pairs: Sequence[tuple[TodoCard, TodoBoard]], principal: Principal
    ) -> list[TodoCardDetail]:
        """Build the whole cards of ``pairs`` with a fixed number of queries per board."""
        cards = [card for card, _board in pairs]
        ids = [card.id for card in cards]
        facts = await self._facts(cards, principal)
        boards = {board.id: board for _card, board in pairs}
        columns = {board_id: await self._columns(board_id) for board_id in boards}
        board_labels = {board_id: await self._labels(board_id) for board_id in boards}
        writable = {
            board_id: await self.access.can_write(board, principal)
            for board_id, board in boards.items()
        }
        items = _by_card(
            (
                await self.session.scalars(
                    select(TodoCheckItem)
                    .where(TodoCheckItem.card_id.in_(ids))
                    .order_by(TodoCheckItem.position, TodoCheckItem.id)
                )
            ).all()
        )
        events = _by_card(
            (
                await self.session.scalars(
                    select(TodoEvent)
                    .where(TodoEvent.card_id.in_(ids))
                    .order_by(TodoEvent.created_at, TodoEvent.id)
                )
            ).all()
        )
        comments = _by_card(
            (
                await self.session.scalars(
                    select(TodoComment)
                    .where(TodoComment.card_id.in_(ids), TodoComment.deleted_at.is_(None))
                    .order_by(TodoComment.created_at, TodoComment.id)
                )
            ).all()
        )
        resolved = await self.links.resolve(_detail_refs(cards, facts, events), principal)
        persons = await person_refs(self.session, _detail_people(cards, events, comments))
        me = await self.access.me(principal)
        files = await self.files.message_attachments(
            "todo_comment", [c.id for card in cards for c in comments.get(card.id, ())]
        )
        parts = _DetailParts(
            facts=facts,
            columns=columns,
            board_labels=board_labels,
            writable=writable,
            items=items,
            events=events,
            comments=comments,
            resolved=resolved,
            persons=persons,
            me=me,
            files=files,
        )
        return [parts.detail(card, board) for card, board in pairs]
