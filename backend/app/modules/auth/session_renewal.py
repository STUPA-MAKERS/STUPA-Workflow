"""Renewal of a long principal session: the periodic check at the IdP.

A principal session lives for many days (`login_settings`). The rights of a principal
come from the IdP groups, and the login caches them (`principal.oidc_groups`). So a long
session needs a fresh look at the IdP, or a removed group keeps its rights until the
session ends.

`renew_principal_session` runs on each request that resolves a session cookie. After
`session_revalidate_hours` since the last check it runs the refresh token grant:

- The IdP accepts: the function stores the new tokens and commits them at once, because
  an IdP that rotates the refresh token has already used up the old one. Then it updates
  the principal (groups, name, email, last login), syncs the gremium memberships, and
  moves `expires_at` to now plus the lifetime of the client (sliding expiry). A claim
  that the refreshed `id_token` leaves out keeps its cached value (OIDC Core 12.2 allows
  a minimal token), so a short token does not remove the groups of a principal.
- The IdP refuses (revoked token, disabled account, merged principal), or the session
  has no refresh token: the function deletes the session. The request is anonymous.
- The IdP is unreachable: the session stays open and a later request tries again. After
  `session_revalidate_grace_hours` without a successful check the session ends. After a
  failure the process does not call the IdP for `_IDP_BACKOFF_SECONDS`, so an outage
  does not hold a database connection and a row lock for each request of each due
  session.
- The session is older than `MAX_SESSION_DAYS` (400): it ends, whatever the IdP says. The
  sliding expiry has no end of its own, so this bound stops a stolen or forgotten
  cookie from living forever.

Parallel requests must not use one refresh token twice, because an IdP that rotates the
token refuses the second use, and that would end the session. The check therefore locks
the row with `FOR UPDATE SKIP LOCKED`. A request that does not get the lock goes on with
the current state; one request renews.

The function commits the request session. It runs inside the auth dependency, before
the route writes anything.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.membership_sync import sync_principal_memberships
from app.modules.auth import oidc
from app.modules.auth.login_settings import load_login_settings, session_days
from app.modules.auth.models import MAX_SESSION_DAYS, AuthSession
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcError, OidcUnavailableError
from app.settings import Settings
from app.shared.errors import ForbiddenError

logger = logging.getLogger(__name__)

#: After an unreachable IdP, the process skips the IdP for this time.
_IDP_BACKOFF_SECONDS = 60.0
#: Monotonic time until which the IdP counts as unreachable in this process.
_idp_retry_after = 0.0


def _monotonic() -> float:
    return time.monotonic()


def _within_grace(row: AuthSession, now: datetime, settings: Settings) -> bool:
    last = row.revalidated_at
    grace = timedelta(hours=settings.session_revalidate_grace_hours)
    return last is not None and now - last < grace


def _too_old(row: AuthSession, now: datetime) -> bool:
    created = row.created_at
    return created is not None and now - created >= timedelta(days=MAX_SESSION_DAYS)


def _due(row: AuthSession, now: datetime, settings: Settings) -> bool:
    """Tell whether the IdP check of the session is due.

    A row without a check time counts as due. The column is NOT NULL, so only a row
    that was never stored lacks it, and an unknown age must not skip the check.
    """
    last = row.revalidated_at
    return last is None or now - last >= timedelta(hours=settings.session_revalidate_hours)


async def session_expiry(db: AsyncSession, client: str, now: datetime) -> datetime:
    """Return the end of a session of `client` that starts or renews at `now`."""
    days = session_days(await load_login_settings(db), client)
    return now + timedelta(days=days)


async def _end(db: AsyncSession, row: AuthSession, reason: str) -> bool:
    logger.info("principal session ended at renewal: %s", reason)
    await db.delete(row)
    await db.commit()
    return False


async def renew_principal_session(
    db: AsyncSession,
    settings: Settings,
    *,
    session: AuthSession,
    principal: PrincipalRow,
    now: datetime,
) -> bool:
    """Check the session at the IdP when the check is due.

    The IdP backoff is one per process. A request that does not get the row lock
    goes on while another request renews the session, and fails when the row is gone
    (logout in another tab, deactivation). ``revalidated_at`` moves only after the
    principal update, so a failure there leaves the check due. ``upsert_principal``
    is imported in the body, because ``service`` pulls in the flow engine, which
    imports ``app.deps``, which imports this module.

    Returns:
        `True` when the session stays valid, `False` when the function ended it.
    """
    global _idp_retry_after
    if not _due(session, now, settings):
        return True
    if _monotonic() < _idp_retry_after and _within_grace(session, now, settings):
        return True
    locked = (
        await db.execute(
            select(AuthSession)
            .where(AuthSession.id == session.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if locked is None:
        still_there = (
            await db.execute(select(AuthSession.id).where(AuthSession.id == session.id))
        ).scalar_one_or_none()
        return still_there is not None
    if not _due(locked, now, settings):
        await db.commit()
        return True
    if _too_old(locked, now):
        return await _end(db, locked, "session older than the absolute lifetime")
    if not settings.oidc_enabled or not locked.refresh_token:
        return await _end(db, locked, "no refresh token")
    cached = oidc.OidcClaims(
        sub=principal.sub,
        email=principal.email,
        name=principal.display_name,
        groups=[str(g) for g in (principal.oidc_groups or [])],
    )
    try:
        token_set = await oidc.refresh_tokens(settings, refresh_token=locked.refresh_token)
        claims = await oidc.verify_refreshed_id_token(
            settings, id_token=token_set["id_token"], cached=cached
        )
    except OidcUnavailableError:
        _idp_retry_after = _monotonic() + _IDP_BACKOFF_SECONDS
        if not _within_grace(locked, now, settings):
            return await _end(db, locked, "idp unreachable past the grace time")
        logger.warning("idp unreachable at session renewal, session kept")
        await db.commit()
        return True
    except OidcError:
        return await _end(db, locked, "idp refused the refresh grant")
    locked.refresh_token = token_set.get("refresh_token") or locked.refresh_token
    locked.id_token = token_set["id_token"]
    await db.commit()
    from app.modules.auth.service import upsert_principal

    try:
        row = await upsert_principal(db, claims)
    except ForbiddenError:
        return await _end(db, locked, "principal merged")
    if row.active is False:
        return await _end(db, locked, "principal deactivated")
    await sync_principal_memberships(db, row)
    locked.revalidated_at = now
    locked.expires_at = await session_expiry(db, locked.client, now)
    await db.commit()
    return True
