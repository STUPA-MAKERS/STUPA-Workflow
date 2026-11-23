"""The permissions of the ticket module and the Bereiche that a person works in.

``ticket.manage`` is the global permission: its holder works on the tickets of every
Bereich. ``ticket.work`` is a gremium permission: a member whose gremium role grants
it works on the tickets of the Bereiche of that Gremium. The report itself
(``POST /tickets``) needs no permission.

``area_scope`` answers the Bereiche of a request principal, and every read and write
of a ticket of the team goes through it. ``area_workers`` answers the persons of a
Bereich for a path without a request principal: the assignee check, the mentions and
the mails.
"""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.people import permission_holders
from app.modules.auth.policy import held_gremium_ids
from app.modules.auth.principal import Principal
from app.modules.gremien.models import GremiumMembership, GremiumRole
from app.modules.tickets.models import PLATFORM_AREA_ID, Ticket, TicketArea, TicketNote

TICKET_MANAGE = "ticket.manage"
TICKET_WORK = "ticket.work"

#: The Bereiche of a person: a set of ids, or None for every Bereich (``ticket.manage``).
type AreaScope = frozenset[UUID] | None

#: ``(id, display_name, email)`` of one account.
type Worker = tuple[UUID, str | None, str | None]

#: The scope of the built-in Bereich alone. It has no Gremium, so only the holders of
#: ``ticket.manage`` work in it.
PLATFORM_ONLY: frozenset[UUID] = frozenset({PLATFORM_AREA_ID})


async def area_scope(session: AsyncSession, principal: Principal) -> AreaScope:
    """Return the Bereiche in which ``principal`` works on tickets.

    ``ticket.manage`` gives None, which stands for every Bereich. Else the result holds
    the Bereiche of the Gremien in which the own gremium role grants ``ticket.work``.
    Both paths obey the OAuth scope cap.
    """
    if principal.has(TICKET_MANAGE):
        return None
    gremien = await held_gremium_ids(session, principal, TICKET_WORK)
    if not gremien:
        return frozenset()
    return frozenset(
        (
            await session.scalars(select(TicketArea.id).where(TicketArea.gremium_id.in_(gremien)))
        ).all()
    )


def works_in(scope: AreaScope, area_id: UUID) -> bool:
    """Tell if a scope holds the Bereich ``area_id``."""
    return scope is None or area_id in scope


def works_anywhere(scope: AreaScope) -> bool:
    """Tell if a scope holds at least one Bereich."""
    return scope is None or bool(scope)


async def area_workers(
    session: AsyncSession,
    areas: Collection[UUID] | None = None,
    *,
    principal_id: UUID | None = None,
) -> list[Worker]:
    """Return the active accounts with the work right in one of ``areas``.

    These are the holders of ``ticket.manage`` and the members whose gremium role
    grants ``ticket.work`` in the Gremium of one of the Bereiche. ``areas`` None
    stands for every Bereich. ``principal_id`` narrows the result to one account. A
    merged or inactive account never counts. The Bereich ``Plattform`` has no Gremium,
    so the Bereich alone reads no membership.
    """
    managers = await permission_holders(session, TICKET_MANAGE, principal_id=principal_id)
    if areas is not None and set(areas) <= PLATFORM_ONLY:
        return managers
    in_areas = (
        select(TicketArea.gremium_id).where(TicketArea.gremium_id.is_not(None))
        if areas is None
        else select(TicketArea.gremium_id).where(
            TicketArea.id.in_(areas), TicketArea.gremium_id.is_not(None)
        )
    )
    members = (
        select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email)
        .join(GremiumMembership, GremiumMembership.principal_id == PrincipalRow.id)
        .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
        .where(
            PrincipalRow.active.is_(True),
            PrincipalRow.merged_into.is_(None),
            GremiumMembership.gremium_id.in_(in_areas),
            GremiumRole.permissions.contains([TICKET_WORK]),
        )
    )
    stmt = members if principal_id is None else members.where(PrincipalRow.id == principal_id)
    found = {pid: (pid, name, email) for pid, name, email in (await session.execute(stmt)).all()}
    return list({**found, **{row[0]: row for row in managers}}.values())


async def works_on_ticket(
    session: AsyncSession, principal: Principal, ticket_id: UUID, *, note: bool = False
) -> bool:
    """Tell if ``principal`` works in the Bereich of one ticket.

    With ``note`` the id names a note of the ticket. A holder of ``ticket.manage``
    passes without a read, also for an unknown id.
    """
    scope = await area_scope(session, principal)
    if scope is None:
        return True
    if not scope:
        return False
    of_ticket = select(Ticket.area_id).where(Ticket.id == ticket_id)
    of_note = (
        select(Ticket.area_id)
        .join(TicketNote, TicketNote.ticket_id == Ticket.id)
        .where(TicketNote.id == ticket_id)
    )
    area_id = await session.scalar(of_note if note else of_ticket)
    return area_id is not None and area_id in scope


async def works_on_tickets(session: AsyncSession, principal: Principal) -> bool:
    """Tell if ``principal`` works in at least one Bereich (the tab "Tickets")."""
    return works_anywhere(await area_scope(session, principal))
