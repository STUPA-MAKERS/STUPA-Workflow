"""The route `/auth/me`: the signed-in person with the facts that the app shell needs.

The route keeps the prefix `/auth`. It is in the module `account` and not in `auth`,
because it asks other modules which tabs a person can see (tickets, substitute pools,
cost centers), and `auth` must import no higher module (§S/backend/python/000649).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.auth import sessions
from app.modules.auth.schemas import (
    GremiumRef,
    MeOut,
)
from app.modules.gremien.models import Gremium
from app.settings import Settings
from app.shared.errors import (
    ProblemDetail,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Document problem+json for the given error status codes."""
    return dict.fromkeys(codes, _PROBLEM)


async def _renew_session_cookie(
    request: Request, response: Response, db: DbSession, settings: Settings
) -> None:
    """Sign the session cookie again and align its lifetime with the session row.

    The app calls `/auth/me` on each start. The session row slides at each check at
    the IdP (`session_renewal`), but the browser keeps the cookie only for its own
    `max_age`. This step carries the new end over to the cookie and renews the
    signature time, so an active user is never logged out by the cookie.
    """
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        return
    now = datetime.now(UTC)
    row = await sessions.load_principal_session(
        db,
        secret=settings.session_secret,
        cookie_value=cookie,
        now=now,
        max_age=sessions.SESSION_COOKIE_MAX_AGE,
    )
    if row is None:
        return
    response.set_cookie(
        settings.session_cookie_name,
        sessions.sign_principal_sid(settings.session_secret, row.sid),
        max_age=max(int((row.expires_at - now).total_seconds()), 0),
        **sessions.cookie_kwargs(settings),  # type: ignore[arg-type]
    )


@router.get("/me", responses=_errors(401, 403))
async def me(
    request: Request,
    response: Response,
    principal: Annotated[Principal, Depends(require_principal())],
    db: DbSession,
    settings: SettingsDep,
) -> MeOut:
    """Return the principal plus the resolved roles, permissions, groups and Gremien.

    For a cookie session, the response also renews the session cookie (see
    `_renew_session_cookie`).
    """
    await _renew_session_cookie(request, response, db, settings)
    return MeOut(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        roles=tuple(sorted(principal.roles)),
        permissions=tuple(sorted(principal.permissions)),
        groups=tuple(sorted(principal.groups)),
        gremien=tuple(await _gremien_for(db, principal.sub)),
        session_manage_gremien=tuple(await _session_manage_gremien(db, principal)),
        gremium_permissions={
            gid: tuple(keys) for gid, keys in (await _gremium_permissions(db, principal)).items()
        },
        has_scoped_budget_view=await _has_scoped_budget_view(db, principal.sub),
        in_substitute_pool=await _in_substitute_pool(db, principal.sub),
        has_reported_tickets=await _has_reported_tickets(db, principal.sub),
    )


async def _has_reported_tickets(db: DbSession, sub: str) -> bool:
    """Tell if `sub` reported a ticket that is not anonymized (the tab "Tickets")."""
    from app.modules.tickets.service import has_reported_tickets

    return await has_reported_tickets(db, sub)


async def _in_substitute_pool(db: DbSession, sub: str) -> bool:
    """Tell if `sub` is in at least one substitute pool.

    The pool is the table `delegation_substitute`. The frontend uses the flag
    to show the meeting timeline to pool substitutes that have no own
    membership.
    """
    from app.modules.gremien.pool import substitute_gremien_for_sub

    return bool(await substitute_gremien_for_sub(db, sub))


async def _has_scoped_budget_view(db: DbSession, sub: str) -> bool:
    """Tell if a Gremium of the principal owns a cost center as visibility root.

    The Gremien are the memberships and the substitute pools (`gremium_reader_ids`).

    The frontend uses the flag to show the budget tab.
    """
    from app.modules.budget.tree_models import Budget
    from app.modules.gremien.gremium_roles import gremium_reader_ids

    member = await gremium_reader_ids(db, sub)
    if not member:
        return False
    hit = await db.scalar(
        select(Budget.id).where(Budget.view_gremium_id.in_(member)).limit(1)
    )
    return hit is not None


async def _session_manage_gremien(db: DbSession, principal: Principal) -> list[UUID]:
    """Return the Gremien that the principal manages through a gremium role.

    The gremium role must hold `session.manage`. This reads the same scope-capped
    source as `MeetingService.can_manage`. The frontend gate for "create meeting"
    and the server decision therefore stay congruent.
    """
    from app.modules.auth.policy import held_gremium_ids

    return sorted(await held_gremium_ids(db, principal, "session.manage"), key=str)


async def _gremium_permissions(
    db: DbSession, principal: Principal
) -> dict[UUID, list[str]]:
    """Return the gremium permissions of the principal per Gremium.

    Each membership counts. The OAuth scope cap removes each key that
    the token scope does not let through. A Gremium without a remaining key stays
    in the map with an empty list, because the membership itself still counts.
    """
    from app.modules.gremien.gremium_roles import GREMIUM_PERMISSIONS, active_gremium_roles

    roles = await active_gremium_roles(db, principal.sub)
    return {
        gid: _scoped_keys(principal, GREMIUM_PERMISSIONS, frozenset(role.permissions or []))
        for gid, role in roles
    }


def _scoped_keys(
    principal: Principal, keys: Iterable[str], held: frozenset[str]
) -> list[str]:
    """Return the `keys` in their order that the role holds and the scope cap lets through."""
    return [p for p in keys if p in held and principal.scope_allows(p)]


async def _gremien_for(db: DbSession, sub: str) -> list[GremiumRef]:
    """Return the Gremien that `sub` is a member of (`gremium_membership`).

    This reads the same source as the server-side visibility logic
    (`gremium_member_ids`). The frontend gate and the server filters therefore agree.
    The global `role_assignment` member role is NOT a gremium membership. A magic-link
    applicant gets an empty list.
    """
    from app.modules.gremien.gremium_roles import gremium_member_ids

    ids = await gremium_member_ids(db, sub)
    if not ids:
        return []
    rows = (
        await db.execute(
            select(Gremium.id, Gremium.name, Gremium.slug)
            .where(Gremium.id.in_(ids))
            .order_by(Gremium.name)
        )
    ).all()
    return [GremiumRef(id=r.id, name=r.name, slug=r.slug) for r in rows]
