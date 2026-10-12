"""Renewal of a long principal session: the periodic check at the IdP.

A principal session lives for many days (`login_settings`). The rights of a principal
come from the IdP groups, and the login caches them (`principal.oidc_groups`). So a long
session needs a fresh look at the IdP, or a removed group keeps its rights until the
session ends.

`renew_principal_session` runs on each request that resolves a session cookie. After
`session_revalidate_hours` since the last check it runs the refresh token grant:

- The IdP accepts: the function updates the principal (groups, name, email, last
  login), syncs the gremium memberships, stores the new tokens, and moves `expires_at`
  to now plus the lifetime of the client (sliding expiry).
- The IdP refuses (revoked token, disabled account, merged principal), or the session
  has no refresh token: the function deletes the session. The request is anonymous.
- The IdP is unreachable: the session stays open and the next request tries again. After
  `session_revalidate_grace_hours` without a successful check the session ends.

Parallel requests must not use one refresh token twice, because an IdP that rotates the
token refuses the second use, and that would end the session. The check therefore locks
the row with `FOR UPDATE SKIP LOCKED`. A request that does not get the lock goes on with
the current state; one request renews.

The function commits the request session. It runs inside the auth dependency, before
the route writes anything.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.membership_sync import sync_principal_memberships
from app.modules.auth import oidc
from app.modules.auth.login_settings import load_login_settings, session_days
from app.modules.auth.models import AuthSession
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oidc import OidcError, OidcUnavailableError
from app.settings import Settings
from app.shared.errors import ForbiddenError

logger = logging.getLogger(__name__)


def _due(row: AuthSession, now: datetime, settings: Settings) -> bool:
    # A row without a check time counts as due: the column is NOT NULL, so only a row
    # that was never stored lacks it, and an unknown age must not skip the check.
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

    Returns:
        `True` when the session stays valid, `False` when the function ended it.
    """
    if not _due(session, now, settings):
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
        # Another request holds the lock and renews the session now.
        return True
    if not _due(locked, now, settings):
        # Another request renewed it between our read and the lock.
        await db.commit()
        return True
    if not settings.oidc_enabled or not locked.refresh_token:
        return await _end(db, locked, "no refresh token")
    try:
        token_set = await oidc.refresh_tokens(settings, refresh_token=locked.refresh_token)
        claims = await oidc.verify_refreshed_id_token(
            settings, id_token=token_set["id_token"], sub=principal.sub
        )
    except OidcUnavailableError:
        last = locked.revalidated_at
        grace = timedelta(hours=settings.session_revalidate_grace_hours)
        if last is None or now - last >= grace:
            return await _end(db, locked, "idp unreachable past the grace time")
        logger.warning("idp unreachable at session renewal, session kept")
        await db.commit()
        return True
    except OidcError:
        return await _end(db, locked, "idp refused the refresh grant")
    # Imported here: `service` pulls in the flow engine, and the flow engine imports
    # `app.deps`, which imports this module. A top-level import closes that cycle.
    from app.modules.auth.service import upsert_principal

    try:
        row = await upsert_principal(db, claims)
    except ForbiddenError:
        return await _end(db, locked, "principal merged")
    if row.active is False:
        return await _end(db, locked, "principal deactivated")
    await sync_principal_memberships(db, row)
    locked.refresh_token = token_set.get("refresh_token") or locked.refresh_token
    locked.id_token = token_set["id_token"]
    locked.revalidated_at = now
    locked.expires_at = await session_expiry(db, locked.client, now)
    await db.commit()
    return True
