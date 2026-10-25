"""Who sees which gremium in the tab "Gremien".

The gate is ``can_view_gremium`` of ``app.modules.auth.policy``, the same rule as the route of
the square logo: the global permission ``gremium.view_all`` (``Principal.has``, so
the admin role and the OAuth scope cap apply), or an active membership now. The
membership path obeys the scope cap too, so a token without the ``read`` scope sees
no gremium. A hidden
gremium and an unknown gremium give the same 404, so the API does not tell that a
gremium exists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.auth.policy import GREMIUM_VIEW_ALL, can_view_gremium
from app.modules.auth.principal import Principal
from app.shared.errors import NotFoundError

GREMIUM_NOT_FOUND = "gremium_not_found"


def views_all(principal: Principal) -> bool:
    """Tell if ``principal`` sees every gremium (``gremium.view_all`` or admin)."""
    return principal.has(GREMIUM_VIEW_ALL)


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
