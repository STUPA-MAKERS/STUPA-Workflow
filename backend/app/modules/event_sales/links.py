"""The link of an Event to a pretix event and its field `Einnahmen-Kostenstelle`.

A link sets the shop of an Event without one to the public address of the pretix event
(§F/integrations/pretix/003083). Each change writes an audit entry with the Event and the
person (003090). The caller checks the rights; no function here commits.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.budget.tree_models import Budget
from app.modules.events.models import Event
from app.modules.pretix.client import PretixEvent
from app.modules.pretix.models import PretixEventLink
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


async def link_of(session: AsyncSession, event_id: uuid.UUID) -> PretixEventLink | None:
    """Return the link of an Event, else None."""
    return await session.scalar(
        select(PretixEventLink)
        .where(PretixEventLink.event_id == event_id)
        .execution_options(populate_existing=True)
    )


async def require_link(session: AsyncSession, event_id: uuid.UUID) -> PretixEventLink:
    """Return the link of an Event.

    Raises:
        NotFoundError: The Event has no link (404 `pretix_link_missing`).
    """
    found = await link_of(session, event_id)
    if found is None:
        raise NotFoundError("The Veranstaltung has no pretix event.", code="pretix_link_missing")
    return found


async def check_free(session: AsyncSession, event_id: uuid.UUID, slug: str) -> None:
    """Refuse a pretix event that another Event links.

    Raises:
        ConflictError: 409 `pretix_event_taken`.
    """
    owner = await session.scalar(
        select(PretixEventLink.event_id).where(PretixEventLink.slug == slug)
    )
    if owner is not None and owner != event_id:
        raise ConflictError("Another Veranstaltung links it.", code="pretix_event_taken")


async def set_link(
    session: AsyncSession, event: Event, found: PretixEvent, sub: str
) -> PretixEventLink:
    """Link the Event to the pretix event; a new pretix event drops the old sales."""
    actor = await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == sub))
    values = {
        "slug": found.slug,
        "name": found.name,
        "date_from": found.date_from,
        "created_by": actor,
    }
    before = await link_of(session, event.id)
    moved = before is not None and before.slug != found.slug
    await session.execute(
        pg_insert(PretixEventLink)
        .values(id=uuid.uuid4(), event_id=event.id, **values)
        .on_conflict_do_update(
            index_elements=[PretixEventLink.event_id],
            set_={**values, **({"sales": None, "sales_ok_at": None} if moved else {})},
        )
    )
    if event.shop_url is None and found.public_url is not None:
        await session.execute(
            update(Event)
            .where(Event.id == event.id)
            .values(shop_url=found.public_url, version=Event.version + 1)
        )
    await audit_record(
        session,
        actor=sub,
        action=AuditAction.PRETIX_LINK,
        target_type="event",
        target_id=str(event.id),
        data={"slug": found.slug},
    )
    return await require_link(session, event.id)


async def remove_link(session: AsyncSession, event_id: uuid.UUID, sub: str) -> None:
    """Remove the link of an Event and write the audit entry."""
    link = await require_link(session, event_id)
    await session.execute(delete(PretixEventLink).where(PretixEventLink.id == link.id))
    await audit_record(
        session,
        actor=sub,
        action=AuditAction.PRETIX_UNLINK,
        target_type="event",
        target_id=str(event_id),
        data={"slug": link.slug},
    )


async def set_income_budget(
    session: AsyncSession, event_id: uuid.UUID, budget_id: uuid.UUID | None, sub: str
) -> PretixEventLink:
    """Set the field `Einnahmen-Kostenstelle` of a linked Event (003086).

    Raises:
        NotFoundError: The Event has no link.
        ValidationProblem: The cost centre does not exist (422 `budget_not_found`).
    """
    link = await require_link(session, event_id)
    if budget_id is not None and await session.get(Budget, budget_id) is None:
        raise ValidationProblem(
            "The cost centre does not exist.",
            code="budget_not_found",
            errors=[{"field": "budgetId", "msg": "not found"}],
        )
    await session.execute(
        update(PretixEventLink)
        .where(PretixEventLink.id == link.id)
        .values(income_budget_id=budget_id)
    )
    await audit_record(
        session,
        actor=sub,
        action=AuditAction.PRETIX_LINK,
        target_type="event",
        target_id=str(event_id),
        data={"slug": link.slug, "incomeBudgetId": str(budget_id) if budget_id else None},
    )
    return await require_link(session, event_id)


async def mark_refreshed(
    session: AsyncSession, link: PretixEventLink | None, now: datetime
) -> None:
    """Keep the moment of the action `Aktualisieren` of an Event."""
    if link is not None:
        await session.execute(
            update(PretixEventLink).where(PretixEventLink.id == link.id).values(refreshed_at=now)
        )
