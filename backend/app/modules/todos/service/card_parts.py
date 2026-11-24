"""The parts of a card: assignees, labels and the checklist."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select

from app.modules.auth.principal import Principal
from app.modules.todos.models import TodoAssignee, TodoCard, TodoCardLabel, TodoCheckItem, TodoLabel
from app.modules.todos.schemas import CheckItemPatch, TodoCardDetail
from app.modules.todos.service.common import _invalid
from app.modules.todos.service.details import DetailOps
from app.shared.errors import NotFoundError


class CardPartOps(DetailOps):
    """Assignee, label and checklist writes on a card."""

    async def add_assignee(
        self, card_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Assign a member of the board (422 ``assignee_not_allowed`` otherwise).

        The board lock makes a parallel identical request wait and then see the row.
        """
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        await self._check_assignees(board, [principal_id])
        present = await self.session.scalar(
            select(TodoAssignee.principal_id).where(
                TodoAssignee.card_id == card.id, TodoAssignee.principal_id == principal_id
            )
        )
        if present is None:
            self.session.add(TodoAssignee(card_id=card.id, principal_id=principal_id))
            self._event(card, "assigned", actor, {"principalId": str(principal_id), "added": True})
            self._touch(board, card)
            await self.session.commit()
            self._mail("assigned", card, [principal_id], actor)
        return await self._detail(card, board, principal)

    async def remove_assignee(
        self, card_id: uuid.UUID, principal_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Remove an assignee; an unknown one changes nothing."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        result = await self.session.execute(
            delete(TodoAssignee).where(
                TodoAssignee.card_id == card.id, TodoAssignee.principal_id == principal_id
            )
        )
        if getattr(result, "rowcount", 0):
            self._event(card, "assigned", actor, {"principalId": str(principal_id), "added": False})
            self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_card_label(
        self, card_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Put a label of the board on the card (422 ``label_not_on_board`` otherwise)."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        label = await self.session.get(TodoLabel, label_id)
        if label is None or label.board_id != board.id:
            raise _invalid("The label is not on this board.", "label_not_on_board", "labelId")
        present = await self.session.scalar(
            select(TodoCardLabel.label_id).where(
                TodoCardLabel.card_id == card.id, TodoCardLabel.label_id == label_id
            )
        )
        if present is None:
            self.session.add(TodoCardLabel(card_id=card.id, label_id=label_id))
            self._touch(board, card)
            await self.session.commit()
        return await self._detail(card, board, principal)

    async def remove_card_label(
        self, card_id: uuid.UUID, label_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Take a label off the card."""
        card, board = await self._card(card_id, principal, lock=True, write=True)
        await self.session.execute(
            delete(TodoCardLabel).where(
                TodoCardLabel.card_id == card.id, TodoCardLabel.label_id == label_id
            )
        )
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def add_check_item(
        self, card_id: uuid.UUID, text: str, principal: Principal
    ) -> TodoCardDetail:
        """Append a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        last = await self.session.scalar(
            select(func.max(TodoCheckItem.position)).where(TodoCheckItem.card_id == card.id)
        )
        value = text.strip() or text
        self.session.add(
            TodoCheckItem(
                id=uuid.uuid4(),
                card_id=card.id,
                text=value,
                done=False,
                position=(last + 1) if last is not None else 0,
            )
        )
        self._event(card, "checklist", actor, {"action": "added", "text": value})
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def _check_item(self, card: TodoCard, item_id: uuid.UUID) -> TodoCheckItem:
        item = await self.session.get(TodoCheckItem, item_id)
        if item is None or item.card_id != card.id:
            raise NotFoundError(f"checklist item {item_id} not found")
        return item

    async def patch_check_item(
        self,
        card_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: CheckItemPatch,
        principal: Principal,
    ) -> TodoCardDetail:
        """Rename, tick or untick, or move a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        item = await self._check_item(card, item_id)
        if payload.text is not None:
            value = payload.text.strip() or payload.text
            if value != item.text:
                item.text = value
                self._event(card, "checklist", actor, {"action": "renamed", "text": value})
        if payload.done is not None and payload.done != item.done:
            item.done = payload.done
            action = "done" if payload.done else "undone"
            self._event(card, "checklist", actor, {"action": action, "text": item.text})
        if payload.position is not None:
            items = list(
                (
                    await self.session.scalars(
                        select(TodoCheckItem)
                        .where(TodoCheckItem.card_id == card.id)
                        .order_by(TodoCheckItem.position, TodoCheckItem.id)
                    )
                ).all()
            )
            others = [i for i in items if i.id != item.id]
            at = min(payload.position, len(others))
            for position, entry in enumerate([*others[:at], item, *others[at:]]):
                entry.position = position
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)

    async def delete_check_item(
        self, card_id: uuid.UUID, item_id: uuid.UUID, principal: Principal
    ) -> TodoCardDetail:
        """Delete a checklist item."""
        actor = await self._actor(principal)
        card, board = await self._card(card_id, principal, lock=True, write=True)
        item = await self._check_item(card, item_id)
        await self.session.delete(item)
        self._event(card, "checklist", actor, {"action": "removed", "text": item.text})
        self._touch(board, card)
        await self.session.commit()
        return await self._detail(card, board, principal)
