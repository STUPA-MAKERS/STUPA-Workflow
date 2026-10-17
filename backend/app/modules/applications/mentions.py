"""The mentionable persons of the comments of one application.

A comment mentions only a person who reads the internal comments of the
application, because the mention mail links the comment and a mention of anybody
else names a person who cannot open it. `mentionable_people` returns exactly the
principals that `resolve_app_read` admits with ``can_see_internal``:

1. the active holders of ``application.read`` or ``application.read_all``
   (``permission_holders``: role assignments, OIDC group mappings, the admin role);
2. the active members of the committee Gremien of the application
   (`committee_gremium_ids`: the budget view Gremien, the vote Gremium, the Gremien
   of the meetings that voted on it), because a member reads through the Gremium
   read scope;
3. the creator (``created_by``), but only while the creator holds
   ``application.manage``, ``application.transition`` or ``application.edit_any``.
   Without one of them the creator reads as the applicant and sees no internal
   comment.

A merged or inactive account never counts, and a person with no name left (an
erased account) drops out. The list is sorted by display name (casefold), then id.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.applications.access import (
    MEMBER_PERMISSIONS,
    READ_ALL_PERMISSION,
    READ_PERMISSION,
    committee_gremium_ids,
)
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.shared.people import PersonRef, permission_holders, person_of

Row = tuple[UUID, str | None, str | None]


async def _committee_members(session: AsyncSession, gremien: set[UUID]) -> list[Row]:
    """Return the active members (any role) of the Gremien, valid now."""
    if not gremien:
        return []
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email)
            .join(GremiumMembership, GremiumMembership.principal_id == PrincipalRow.id)
            .where(
                GremiumMembership.gremium_id.in_(gremien),
                or_(GremiumMembership.valid_from.is_(None), GremiumMembership.valid_from <= now),
                or_(GremiumMembership.valid_until.is_(None), GremiumMembership.valid_until > now),
                PrincipalRow.active.is_(True),
                PrincipalRow.merged_into.is_(None),
            )
            .distinct()
        )
    ).all()
    return [(pid, name, email) for pid, name, email in rows]


async def _creator_as_member(session: AsyncSession, application_id: UUID) -> list[Row]:
    """Return the creator when the creator holds a member right, else nothing."""
    created_by = await session.scalar(
        select(Application.created_by).where(Application.id == application_id)
    )
    if created_by is None:
        return []
    creator = await session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == created_by))
    if creator is None:
        return []
    for perm in MEMBER_PERMISSIONS:
        rows = await permission_holders(session, perm, principal_id=creator)
        if rows:
            return rows
    return []


async def mentionable_people(session: AsyncSession, application_id: UUID) -> list[PersonRef]:
    """Return the persons whom a comment on the application may mention.

    The caller checked that the application exists and that it reads the internal
    comments.
    """
    rows: list[Row] = []
    rows += await permission_holders(session, READ_PERMISSION)
    rows += await permission_holders(session, READ_ALL_PERMISSION)
    rows += await _committee_members(session, await committee_gremium_ids(session, application_id))
    rows += await _creator_as_member(session, application_id)
    people: dict[UUID, PersonRef] = {}
    for pid, name, email in rows:
        ref = person_of(pid, name, email)
        if ref.principal_id is not None:
            people[pid] = ref
    return sorted(
        people.values(),
        key=lambda p: ((p.display_name or "").casefold(), str(p.principal_id)),
    )


async def mentionable_ids(session: AsyncSession, application_id: UUID) -> set[UUID]:
    """Return the ids of `mentionable_people`."""
    return {
        p.principal_id
        for p in await mentionable_people(session, application_id)
        if p.principal_id is not None
    }
