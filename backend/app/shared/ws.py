"""WebSocket handshake helpers that several modules share.

The live-vote channels and the to-do channel authenticate the same way: the
``Origin`` header must be on the allowlist (CSWSH), and the session cookie resolves
to a principal. Only the session cookie counts, never an OAuth token, because the
sockets serve the browser.

Close codes (application-defined, 4000–4999): ``4401`` no session, ``4403`` not
allowed (also a foreign origin and the connection cap), ``4404`` unknown.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import rbac, sessions
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.auth.session_renewal import renew_principal_session
from app.settings import Settings

logger = logging.getLogger("app.livevote")

WS_UNAUTHENTICATED = 4401
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404


def _allowed_origins(settings: Settings) -> set[str]:
    """Return the allowed WebSocket origins.

    The set holds the public base URL and the configured CORS origins. Every
    entry is normalized to `scheme://host[:port]` without a path and without a
    trailing slash. This matches the `Origin` header of a browser.
    """
    origins = {o.rstrip("/") for o in settings.cors_allow_origins if o}
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        origins.add(base)
    return origins


def origin_allowed(origin: str | None, settings: Settings) -> bool:
    """Protect the WebSocket handshake against CSRF.

    The double-submit CSRF middleware does not run for a WebSocket upgrade. A
    cookie-authenticated cross-origin upgrade (CSWSH) would pass. This function
    therefore checks the `Origin` header here, independent of SameSite.

    A client that is not a browser (native, MCP, CLI or test) sends no `Origin`
    header. The handshake then relies on the cookie and session check alone,
    because such a client is not open to CSRF. A header that is present MUST be
    on the allowlist. Without configured origins, the default, there is no gate.
    """
    if origin is None:
        return True
    allowed = _allowed_origins(settings)
    if not allowed:
        return True
    return origin.rstrip("/") in allowed


async def _neutralize_close(websocket: WebSocket) -> None:
    """Make `websocket.close` a no-op, so a second close does nothing.

    After the 4403 close of this module, the follow-up `close(4401)` of the
    router would raise `RuntimeError` in Starlette. The message reads "Cannot
    call send once a close message has been sent". The replaced bound method
    absorbs the second close.
    """

    async def _noop(code: int = 1000, reason: str | None = None) -> None:
        return None

    websocket.close = _noop


async def resolve_ws_principal(
    websocket: WebSocket, db: AsyncSession, settings: Settings
) -> Principal | None:
    """Resolve the session cookie of the WebSocket handshake to a principal.

    The function checks the `Origin` header against the allowlist first. See
    `origin_allowed` for the CSWSH protection. On a mismatch it closes the
    handshake with `4403`.

    Returns:
        The principal, or `None` when the origin, the cookie or the session is
        invalid.
    """
    # Close here on a foreign origin, then neutralize the later close of the
    # router.
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin, settings):
        logger.info("ws handshake rejected: disallowed origin %r", origin)
        await websocket.close(code=WS_FORBIDDEN)
        await _neutralize_close(websocket)
        return None
    cookie = websocket.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None
    now = datetime.now(UTC)
    session = await sessions.load_principal_session(
        db,
        secret=settings.session_secret,
        cookie_value=cookie,
        now=now,
        max_age=sessions.SESSION_COOKIE_MAX_AGE,
    )
    if session is None:
        return None
    row = (
        await db.execute(select(PrincipalRow).where(PrincipalRow.id == session.principal_id))
    ).scalar_one_or_none()
    if row is None or row.active is False:
        return None
    # A long session checks the account at the IdP from time to time. The check can
    # end the session, and it can change the groups and memberships of the row.
    if not await renew_principal_session(db, settings, session=session, principal=row, now=now):
        return None
    if row.active is False:
        return None
    return await rbac.resolve_principal(db, row, now)
