"""Who sees which gremium in the tab "Gremien".

A principal sees a gremium when one of these is true:

* the principal has an active membership in it now: the membership is valid now
  (``valid_from``/``valid_until``) and the principal row is active. This is the rule
  of the member count on the admin page;
* the principal holds the global read permission ``gremium.view_all``;
* the principal has the admin role.

``Principal.has`` covers the last two: it applies the admin bypass and the OAuth
scope cap. A hidden gremium and an unknown gremium give the same 404, so the API does
not tell that a gremium exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium, GremiumMembership
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.shared.errors import NotFoundError

VIEW_ALL = "gremium.view_all"
GREMIUM_NOT_FOUND = "gremium_not_found"


def membership_active_clause(now: datetime) -> ColumnElement[bool]:
    """Return the clause of a membership that is valid at ``now`` (half-open term)."""
    return ((GremiumMembership.valid_from.is_(None)) | (GremiumMembership.valid_from <= now)) & (
        (GremiumMembership.valid_until.is_(None)) | (GremiumMembership.valid_until > now)
    )


def views_all(principal: Principal) -> bool:
    """Tell if ``principal`` sees every gremium (``gremium.view_all`` or admin)."""
    return principal.has(VIEW_ALL)


async def member_gremium_ids(
    session: AsyncSession, principal: Principal, now: datetime | None = None
) -> set[UUID]:
    """Return the gremien in which ``principal`` has an active membership now."""
    at = now or datetime.now(UTC)
    rows = await session.scalars(
        select(GremiumMembership.gremium_id)
        .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
        .where(
            PrincipalRow.sub == principal.sub,
            PrincipalRow.active.is_(True),
            membership_active_clause(at),
        )
    )
    return set(rows.all())


async def can_view_gremium(session: AsyncSession, principal: Principal, gremium_id: UUID) -> bool:
    """Tell if ``principal`` sees the gremium ``gremium_id`` in the tab."""
    if views_all(principal):
        return True
    return gremium_id in await member_gremium_ids(session, principal)


async def require_gremium(session: AsyncSession, principal: Principal, gremium_id: UUID) -> Gremium:
    """Return the gremium when ``principal`` sees it.

    Raises:
        NotFoundError: The gremium does not exist or ``principal`` does not see it
            (404 ``gremium_not_found`` in both cases).
    """
    gremium = await session.get(Gremium, gremium_id)
    if gremium is None or not await can_view_gremium(session, principal, gremium_id):
        raise NotFoundError("gremium not found", code=GREMIUM_NOT_FOUND)
    return gremium
