"""Changes of the team on a ticket: status, assignee, Bereich, Kategorie, duplicate."""

from __future__ import annotations

import uuid

from app.modules.auth.principal import Principal
from app.modules.tickets.access import AreaScope, area_workers
from app.modules.tickets.models import (
    CLOSED_STATUSES,
    PLATFORM_AREA_ID,
    Ticket,
    TicketArea,
    TicketCategory,
)
from app.modules.tickets.schemas import TicketDetail, TicketPatch
from app.modules.tickets.service.common import _area_of_id, _id_or_none, _now, principal_id_of
from app.modules.tickets.service.reads import ReadOps
from app.modules.tickets.webhook_fields import emit_ticket_status
from app.shared.errors import ValidationProblem


class ChangeOps(ReadOps):
    """The ``patch`` of a ticket and its parts."""

    async def patch(
        self,
        ticket_id: uuid.UUID,
        payload: TicketPatch,
        principal: Principal,
        *,
        areas: AreaScope = None,
    ) -> TicketDetail:
        """Change status, assignee, Kategorie or Bereich, and write one event per change.

        A status change into ``done`` or ``rejected`` sets ``closed_at``, a reopen
        clears it. ``waiting`` is an open status and leaves ``closed_at`` empty.
        ``duplicateOfId`` goes with ``status: rejected`` only and names
        another ticket. ``completeTodos`` goes with ``done`` or ``rejected`` only.

        ``areaId`` moves the ticket to another Bereich, also to one outside ``areas``.
        The move clears the Kategorie, and it clears the assignee who has no work right
        in the new Bereich. The other fields of the same call apply to the new Bereich.
        The answer is the ticket after the change, also when the caller cannot read it
        any more.

        Raises:
            NotFoundError: No ticket has this id in the Bereiche ``areas`` (HTTP 404).
            ValidationProblem: ``assignee_not_allowed``, ``duplicate_invalid``,
                ``area_invalid``, ``category_invalid``, or ``completeTodos`` without a
                closing status (HTTP 422).
        """
        ticket = await self._get(ticket_id, areas=areas)
        fields = payload.model_fields_set
        actor = await principal_id_of(self.session, principal.sub)
        duplicate = await self._duplicate_target(ticket, payload)
        if payload.complete_todos and payload.status not in CLOSED_STATUSES:
            raise ValidationProblem(
                "completeTodos goes with the status done or rejected.",
                errors=[{"field": "completeTodos", "msg": "needs status done or rejected"}],
            )
        target = await self._move_target(ticket, payload)
        area_id = target.id if target is not None else _area_of_id(ticket)
        if (
            "assignee_id" in fields
            and payload.assignee_id is not None
            and not await area_workers(
                self.session, frozenset({area_id}), principal_id=payload.assignee_id
            )
        ):
            raise ValidationProblem(
                "The assignee must have the work right in the Bereich of the ticket.",
                code="assignee_not_allowed",
                errors=[{"field": "assigneeId", "msg": "no work right in the Bereich"}],
            )
        category = await self._category_target(area_id, payload)
        status, kind = payload.status, payload.kind
        new_status = (
            status
            if status is not None and (status != ticket.status or duplicate is not None)
            else None
        )
        moved = target is not None and await self._move(ticket, target, actor)
        assignee_changes = "assignee_id" in fields and payload.assignee_id != ticket.assignee_id
        new_kind = kind if kind is not None and kind != ticket.kind else None
        category_changes = "category_id" in fields and payload.category_id != ticket.category_id
        if new_status is not None:
            old_status = ticket.status
            self._set_status(ticket, new_status, duplicate, actor)
            await emit_ticket_status(self.session, ticket, old=old_status, new=new_status)
        if assignee_changes:
            self._event(
                ticket,
                "assignee",
                actor,
                {
                    "from": _id_or_none(ticket.assignee_id),
                    "to": _id_or_none(payload.assignee_id),
                },
            )
            ticket.assignee_id = payload.assignee_id
        if new_kind is not None:
            self._event(ticket, "kind", actor, {"from": ticket.kind, "to": new_kind})
            ticket.kind = new_kind
        if category_changes:
            await self._set_category(ticket, category, actor)
        changes = (new_status is not None, assignee_changes, new_kind is not None)
        if any(changes) or category_changes or moved:
            ticket.updated_at = _now()
        await self.session.commit()
        if payload.complete_todos and self.todos is not None:
            await self.todos.complete(ticket.id, principal)
        return await self.detail(ticket.id, principal)

    async def _move_target(self, ticket: Ticket, payload: TicketPatch) -> TicketArea | None:
        """Return the Bereich that a patch moves the ticket to, else None.

        Raises:
            ValidationProblem: ``areaId`` names no Bereich (HTTP 422, ``area_invalid``).
        """
        if payload.area_id is None or payload.area_id == ticket.area_id:
            return None
        target = await self.session.get(TicketArea, payload.area_id)
        if target is None:
            raise ValidationProblem(
                "areaId names no Bereich.",
                code="area_invalid",
                errors=[{"field": "areaId", "msg": "unknown Bereich"}],
            )
        return target

    async def _category_target(
        self, area_id: uuid.UUID, payload: TicketPatch
    ) -> TicketCategory | None:
        """Return the Kategorie that a patch sets, after the check against the Bereich.

        ``kind`` is the Kategorie of ``Plattform`` only, and ``categoryId`` names a
        Kategorie of the Bereich of the ticket.

        Raises:
            ValidationProblem: ``kind`` outside ``Plattform``, or a ``categoryId`` of
                another Bereich (HTTP 422, ``category_invalid``).
        """
        category = (
            await self.session.get(TicketCategory, payload.category_id)
            if payload.category_id is not None
            else None
        )
        foreign = payload.category_id is not None and (
            category is None or category.area_id != area_id
        )
        if foreign or (payload.kind is not None and area_id != PLATFORM_AREA_ID):
            raise ValidationProblem(
                "The Kategorie does not belong to the Bereich of the ticket.",
                code="category_invalid",
                errors=[{"field": "categoryId", "msg": "not a Kategorie of the Bereich"}],
            )
        return category

    async def _move(self, ticket: Ticket, target: TicketArea, actor: uuid.UUID | None) -> bool:
        """Move a ticket to the Bereich ``target`` and write the ``area`` event.

        The Kategorie goes. The assignee goes when the person has no work right in the
        new Bereich. The event keeps both names, so the timeline reads after a rename
        or a delete of a Bereich.
        """
        source = await self.session.get(TicketArea, ticket.area_id)
        keeps = ticket.assignee_id is not None and await area_workers(
            self.session, frozenset({target.id}), principal_id=ticket.assignee_id
        )
        self._event(
            ticket,
            "area",
            actor,
            {
                "from": str(ticket.area_id),
                "to": str(target.id),
                "fromName": source.name if source is not None else None,
                "toName": target.name,
            },
        )
        values: dict[str, object] = {
            "area_id": target.id,
            "kind": None,
            "category_id": None,
            **({} if keeps else {"assignee_id": None}),
        }
        for name, value in values.items():
            setattr(ticket, name, value)
        return True

    async def _set_category(
        self, ticket: Ticket, category: TicketCategory | None, actor: uuid.UUID | None
    ) -> None:
        """Set or clear the Kategorie and write the ``category`` event with both names."""
        before = (
            await self.session.get(TicketCategory, ticket.category_id)
            if ticket.category_id is not None
            else None
        )
        self._event(
            ticket,
            "category",
            actor,
            {
                "from": before.name if before is not None else None,
                "to": category.name if category is not None else None,
            },
        )
        ticket.category_id = category.id if category is not None else None

    async def _duplicate_target(self, ticket: Ticket, payload: TicketPatch) -> Ticket | None:
        if payload.duplicate_of_id is None:
            return None
        target = (
            await self.session.get(Ticket, payload.duplicate_of_id)
            if payload.status == "rejected" and payload.duplicate_of_id != ticket.id
            else None
        )
        if target is None:
            raise ValidationProblem(
                "duplicateOfId names another ticket and goes with status rejected.",
                code="duplicate_invalid",
                errors=[{"field": "duplicateOfId", "msg": "invalid duplicate"}],
            )
        return target
