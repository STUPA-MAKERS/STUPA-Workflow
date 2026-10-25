"""The shared policy of the gremium permissions.

This module is the one place for a gremium-scoped permission check. A global
permission goes through ``Principal.has``. A gremium permission (``session.manage``,
``vote.manage``, ``protocol.write``, ``protocol.finalize``, ``todo.write``,
``todo.configure``) never enters ``Principal.permissions``, so ``has`` cannot cap
it. The functions here apply the OAuth scope cap (``Principal.scope_allows``) to
every path, the admin bypass included:

* ``admin_bypass`` — the admin role uses ``perm`` in every gremium.
* ``held_gremium_ids`` / ``holds_gremium_permission`` — the own gremium role only.
* ``gremium_ids_with`` / ``has_gremium_permission`` — the admin bypass or the own
  gremium role. ``gremium_ids_with`` gives ``ALL_GREMIEN`` for the bypass.
* ``can_view_gremium`` / ``gremium_view_scope`` — the visibility of a gremium.

The sub-based ``gremium_roles.gremium_ids_with_permission`` stays for the system
and roster paths that have no request principal (principal resolution, quorum
count, delegation eligibility, mail recipients). Bug F16: a ``read`` token of a
chair or of the minute-taker could manage the meeting and write the minutes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Final, final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin import gremium_roles
from app.modules.auth.principal import Principal

GREMIUM_VIEW_ALL: Final = "gremium.view_all"


@final
class AllGremien:
    """Every gremium: the answer of ``gremium_ids_with`` for the admin bypass.

    ``gremium_id in ALL_GREMIEN`` is True for every id, so a caller that only tests
    membership treats the bypass and a set the same way.
    """

    __slots__ = ()

    def __contains__(self, gremium_id: object) -> bool:
        return True

    def __repr__(self) -> str:
        return "ALL_GREMIEN"


ALL_GREMIEN: Final = AllGremien()

type GremiumScope = set[UUID] | AllGremien


def expand(scope: GremiumScope, every: Iterable[UUID]) -> set[UUID]:
    """Return ``scope`` as a set: the ids of ``every`` for ``ALL_GREMIEN``."""
    if isinstance(scope, AllGremien):
        return set(every)
    return scope


def admin_bypass(principal: Principal, perm: str) -> bool:
    """Tell if the admin role lets ``principal`` use ``perm`` in every gremium.

    The bypass applies the scope cap: an admin token without ``perm`` in its scope
    does not get it.
    """
    return principal.is_admin and principal.scope_allows(perm)


async def held_gremium_ids(
    session: AsyncSession,
    principal: Principal,
    perm: str,
    now: datetime | None = None,
) -> set[UUID]:
    """Return the gremien where the own gremium role grants ``perm``, scope-capped.

    The admin bypass does not apply. A scoped OAuth token gets the empty set when
    its scope does not contain ``perm``.
    """
    if not principal.scope_allows(perm):
        return set()
    return await gremium_roles.gremium_ids_with_permission(session, principal.sub, perm, now)


async def holds_gremium_permission(
    session: AsyncSession,
    principal: Principal,
    perm: str,
    gremium_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Tell if the own gremium role grants ``perm`` in ``gremium_id`` (no admin bypass)."""
    return gremium_id in await held_gremium_ids(session, principal, perm, now)


async def gremium_ids_with(
    session: AsyncSession,
    principal: Principal,
    perm: str,
    now: datetime | None = None,
) -> GremiumScope:
    """Return the gremien where ``principal`` uses ``perm``: bypass or own role.

    Returns:
        ``ALL_GREMIEN`` for the admin bypass, else the ids of ``held_gremium_ids``.
    """
    if admin_bypass(principal, perm):
        return ALL_GREMIEN
    return await held_gremium_ids(session, principal, perm, now)


async def has_gremium_permission(
    session: AsyncSession,
    principal: Principal,
    perm: str,
    gremium_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Tell if ``principal`` uses ``perm`` in ``gremium_id``: bypass or own role."""
    return gremium_id in await gremium_ids_with(session, principal, perm, now)


async def can_view_gremium(
    session: AsyncSession,
    principal: Principal,
    gremium_id: UUID,
    now: datetime | None = None,
) -> bool:
    """Tell if ``principal`` may see the Gremium ``gremium_id``.

    A principal sees a Gremium when it holds the global permission
    ``gremium.view_all`` (the admin role included, scope-capped through ``has``),
    or when it is an active member of the Gremium now. The membership path also
    obeys the OAuth scope cap, so a token without the ``read`` scope sees no
    Gremium. A read route that refuses answers 404, not 403, so the answer does
    not tell that the Gremium exists.
    """
    visible = await gremium_view_scope(session, principal, now)
    return visible is None or gremium_id in visible


async def gremium_view_scope(
    session: AsyncSession,
    principal: Principal,
    now: datetime | None = None,
) -> set[UUID] | None:
    """Return the Gremien that ``principal`` may see: ``None`` for every Gremium.

    The set form of ``can_view_gremium``, for a reader that checks many Gremien at
    once (the to-do links): ``gremium.view_all`` gives ``None``, a token without the
    ``read`` scope the empty set, anyone else the active memberships now.
    """
    if principal.has(GREMIUM_VIEW_ALL):
        return None
    if not principal.scope_allows(GREMIUM_VIEW_ALL):
        return set()
    return await gremium_roles.gremium_member_ids(session, principal.sub, now)
