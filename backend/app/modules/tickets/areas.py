"""The Bereiche of the ticket module and their Kategorien.

A Bereich separates the tickets, the rights and the settings of one team. The
built-in Bereich ``Plattform`` takes the reports of the help menu: it has no Gremium,
its Kategorien are the four kinds of a report, and only its switches change. Every
other Bereich holds its own ordered list of Kategorien.

``TicketAreaService.listing`` serves the team, and the other methods serve the admin
page "Hilfe & Tickets". Every change writes an audit entry (``config_change``, target
type ``ticket_area``). The service does not commit; the router does.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import groupby

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.gremien.models import Gremium
from app.modules.tickets.access import AreaScope, works_in
from app.modules.tickets.models import Ticket, TicketArea, TicketCategory
from app.modules.tickets.schemas import (
    TicketAreaCreate,
    TicketAreaOut,
    TicketAreaPatch,
    TicketCategoryIn,
    TicketCategoryOut,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

#: The problem code of a second Bereich with a used name.
AREA_NAME_TAKEN = "ticket_area_name_taken"
#: The problem code of a change that the Bereich ``Plattform`` does not take.
PLATFORM_FIXED = "ticket_area_platform_fixed"
#: The problem code of the delete of a Bereich that holds a ticket.
AREA_HAS_TICKETS = "ticket_area_has_tickets"
#: The problem code of a list of Kategorien that names a foreign id or a name twice.
CATEGORIES_INVALID = "ticket_categories_invalid"
#: The fields of ``Plattform`` that no admin changes.
_FIXED_FIELDS = frozenset({"name", "gremium_id", "categories"})


def _area_out(
    area: TicketArea, categories: Sequence[TicketCategory], scope: AreaScope
) -> TicketAreaOut:
    return TicketAreaOut(
        id=area.id,
        name=area.name,
        gremium_id=area.gremium_id,
        platform=area.platform,
        notify_new=area.notify_new,
        categories=tuple(TicketCategoryOut(id=c.id, name=c.name) for c in categories),
        mine=works_in(scope, area.id),
    )


def _clean(name: str) -> str:
    return name.strip()


def _checked_names(categories: Sequence[TicketCategoryIn]) -> list[str]:
    """Return the trimmed names of a list of Kategorien.

    Raises:
        ValidationProblem: A blank name, or two equal names without regard to case
            (HTTP 422, ``ticket_categories_invalid``).
    """
    names = [_clean(c.name) for c in categories]
    if any(not name for name in names) or len({n.casefold() for n in names}) != len(names):
        raise ValidationProblem(
            "Each Kategorie needs its own name.",
            code=CATEGORIES_INVALID,
            errors=[{"field": "categories", "msg": "blank or duplicate name"}],
        )
    return names


@dataclass(frozen=True, slots=True)
class TicketAreaService:
    """Bereich operations bound to an ``AsyncSession``."""

    session: AsyncSession

    async def listing(self, scope: AreaScope = None) -> list[TicketAreaOut]:
        """List every Bereich, ``Plattform`` first, then by name.

        ``scope`` sets ``mine``: the Bereiche in which the caller works.
        """
        areas = list(
            (
                await self.session.scalars(
                    select(TicketArea).order_by(TicketArea.platform.desc(), TicketArea.name)
                )
            ).all()
        )
        by_area = await self._categories()
        return [_area_out(area, by_area.get(area.id, ()), scope) for area in areas]

    async def _categories(
        self, area_id: uuid.UUID | None = None
    ) -> Mapping[uuid.UUID, Sequence[TicketCategory]]:
        """Return the Kategorien per Bereich in their order."""
        every = select(TicketCategory).order_by(
            TicketCategory.area_id, TicketCategory.position, TicketCategory.name
        )
        stmt = every if area_id is None else every.where(TicketCategory.area_id == area_id)
        rows = list((await self.session.scalars(stmt)).all())
        return {key: list(group) for key, group in groupby(rows, key=lambda c: c.area_id)}

    async def get(self, area_id: uuid.UUID) -> TicketArea:
        """Return one Bereich.

        Raises:
            NotFoundError: No Bereich has this id (HTTP 404).
        """
        area = await self.session.get(TicketArea, area_id)
        if area is None:
            raise NotFoundError(f"ticket area {area_id} not found")
        return area

    async def _out(self, area: TicketArea) -> TicketAreaOut:
        return _area_out(area, (await self._categories(area.id)).get(area.id, ()), None)

    async def _check_name(self, name: str, *, keep: uuid.UUID | None = None) -> None:
        """Refuse a name that another Bereich has, without regard to case.

        Raises:
            ConflictError: The name is taken (HTTP 409, ``ticket_area_name_taken``).
        """
        rows = (await self.session.execute(select(TicketArea.id, TicketArea.name))).tuples().all()
        if any(n.casefold() == name.casefold() and found != keep for found, n in rows):
            raise ConflictError("A Bereich with this name exists.", code=AREA_NAME_TAKEN)

    async def _check_gremium(self, gremium_id: uuid.UUID | None) -> None:
        """Refuse a Gremium that does not exist.

        Raises:
            ValidationProblem: No Gremium has this id (HTTP 422).
        """
        if gremium_id is not None and await self.session.get(Gremium, gremium_id) is None:
            raise ValidationProblem(
                "The Gremium does not exist.",
                errors=[{"field": "gremiumId", "msg": "unknown gremium"}],
            )

    async def create(self, payload: TicketAreaCreate, actor: str) -> TicketAreaOut:
        """Store a new Bereich with its Kategorien.

        Raises:
            ConflictError: The name is taken (HTTP 409).
            ValidationProblem: An unknown Gremium, or a blank or duplicate Kategorie
                (HTTP 422).
        """
        name = _clean(payload.name)
        names = _checked_names(payload.categories)
        await self._check_name(name)
        await self._check_gremium(payload.gremium_id)
        area = TicketArea(
            id=uuid.uuid4(),
            name=name,
            gremium_id=payload.gremium_id,
            platform=False,
            notify_new=payload.notify_new,
        )
        self.session.add(area)
        await self.session.flush()
        self.session.add_all(
            TicketCategory(id=uuid.uuid4(), area_id=area.id, name=category, position=index)
            for index, category in enumerate(names)
        )
        await self.session.flush()
        await self._audit(actor, area.id, {"created": True, "name": name})
        return await self._out(area)

    async def patch(
        self, area_id: uuid.UUID, payload: TicketAreaPatch, actor: str
    ) -> TicketAreaOut:
        """Change the name, the Gremium, the switch or the Kategorien of a Bereich.

        Raises:
            NotFoundError: No Bereich has this id (HTTP 404).
            ConflictError: The name is taken, or a fixed field of ``Plattform``
                (HTTP 409, ``ticket_area_platform_fixed``).
            ValidationProblem: An unknown Gremium, or a list of Kategorien with a
                foreign id, a blank name or a duplicate name (HTTP 422).
        """
        area = await self.get(area_id)
        fields = payload.model_fields_set
        if area.platform and fields & _FIXED_FIELDS:
            raise ConflictError(
                "The Bereich Plattform keeps its name, its Kategorien and has no Gremium.",
                code=PLATFORM_FIXED,
            )
        name = _clean(payload.name) if payload.name is not None else None
        if name is not None:
            await self._check_name(name, keep=area.id)
        if "gremium_id" in fields:
            await self._check_gremium(payload.gremium_id)
        values: dict[str, object] = {
            **({"name": name} if name is not None else {}),
            **({"gremium_id": payload.gremium_id} if "gremium_id" in fields else {}),
            **({"notify_new": payload.notify_new} if payload.notify_new is not None else {}),
        }
        for column, value in values.items():
            setattr(area, column, value)
        if "categories" in fields and payload.categories is not None:
            await self._save_categories(area.id, payload.categories)
        await self.session.flush()
        await self._audit(actor, area.id, {"fields": sorted(fields)})
        return await self._out(area)

    async def _save_categories(
        self, area_id: uuid.UUID, wanted: Sequence[TicketCategoryIn]
    ) -> None:
        """Replace the Kategorien of a Bereich by the ordered list ``wanted``.

        A stored Kategorie that the list leaves out is deleted, and the database
        clears it on its tickets.

        Raises:
            ValidationProblem: An id of another Bereich, an id twice, a blank name or
                a duplicate name (HTTP 422, ``ticket_categories_invalid``).
        """
        names = _checked_names(wanted)
        stored = {c.id: c for c in (await self._categories(area_id)).get(area_id, ())}
        kept = [c.id for c in wanted if c.id is not None]
        if len(set(kept)) != len(kept) or not set(kept) <= set(stored):
            raise ValidationProblem(
                "A Kategorie of the list does not belong to the Bereich.",
                code=CATEGORIES_INVALID,
                errors=[{"field": "categories", "msg": "unknown or duplicate id"}],
            )
        gone = set(stored) - set(kept)
        if gone:
            await self.session.execute(delete(TicketCategory).where(TicketCategory.id.in_(gone)))
        for index, (category, name) in enumerate(zip(wanted, names, strict=True)):
            row = stored.get(category.id) if category.id is not None else None
            if row is None:
                self.session.add(
                    TicketCategory(id=uuid.uuid4(), area_id=area_id, name=name, position=index)
                )
            else:
                for column, value in (("name", name), ("position", index)):
                    setattr(row, column, value)

    async def delete(self, area_id: uuid.UUID, actor: str) -> None:
        """Delete a Bereich that holds no ticket, with its Kategorien.

        Raises:
            NotFoundError: No Bereich has this id (HTTP 404).
            ConflictError: The Bereich is ``Plattform`` (``ticket_area_platform_fixed``)
                or holds a ticket (``ticket_area_has_tickets``) (HTTP 409).
        """
        area = await self.get(area_id)
        if area.platform:
            raise ConflictError("The Bereich Plattform cannot be deleted.", code=PLATFORM_FIXED)
        used = await self.session.scalar(
            select(Ticket.id).where(Ticket.area_id == area.id).limit(1)
        )
        if used is not None:
            raise ConflictError("The Bereich holds tickets.", code=AREA_HAS_TICKETS)
        await self.session.delete(area)
        await self.session.flush()
        await self._audit(actor, area_id, {"deleted": True, "name": area.name})

    async def _audit(self, actor: str, area_id: uuid.UUID, data: dict[str, object]) -> None:
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.CONFIG_CHANGE,
            target_type="ticket_area",
            target_id=str(area_id),
            data=data,
        )
