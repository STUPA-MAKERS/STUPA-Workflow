"""Auth orchestration.

This module binds the primitives (sessions, oidc, rbac) to the database and the
settings. It covers the OIDC callback (code to token to session) and the principal
upsert. The login of an applicant (magic link, e-mail login) is in
`app.modules.applications` (§S/backend/python/000649).

Pure HTTP wiring lives in the router. This module holds only domain logic and I/O.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth import oidc, sessions
from app.modules.auth.bootstrap import (
    ensure_admin_for_principal,
    ensure_member_for_principal,
)
from app.modules.auth.models import SESSION_CLIENT_WEB
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.session_renewal import session_expiry
from app.modules.gremien.membership_sync import sync_principal_memberships
from app.settings import Settings
from app.shared.errors import ForbiddenError

logger = logging.getLogger("app.auth")

def _now() -> datetime:
    return datetime.now(UTC)


async def upsert_principal(db: AsyncSession, claims: oidc.OidcClaims) -> PrincipalRow:
    """Create or update a principal by the OIDC `sub` (identity and group cache).

    Raises:
        ForbiddenError: The `sub` belongs to a principal that an admin merged into
            another one (code `account_merged`). The login fails closed and changes
            nothing: the old row stays a locked reference. It does not log in as the
            new principal either, because only the IdP `sub` of the new principal
            proves that identity.
    """
    existing = (
        await db.execute(select(PrincipalRow).where(PrincipalRow.sub == claims.sub))
    ).scalar_one_or_none()
    if existing is not None and existing.merged_into is not None:
        raise ForbiddenError(
            "This account was merged into another account. Log in with that account.",
            code="account_merged",
        )
    row = existing if existing is not None else PrincipalRow(sub=claims.sub)
    if existing is None:
        db.add(row)
    row.email = claims.email
    row.display_name = claims.name
    row.oidc_groups = list(claims.groups)
    row.last_login = _now()
    await db.flush()
    return row


async def oidc_callback(
    db: AsyncSession,
    settings: Settings,
    *,
    code: str,
    verifier: str,
    nonce: str,
    client: str = SESSION_CLIENT_WEB,
) -> tuple[str, PrincipalRow]:
    """Exchange the code, verify the token, upsert the principal and open a session.

    `client` (`web` or `pwa`) selects the session lifetime from `login_settings`.

    A deactivated principal fails closed here, so no session is created. A bootstrap
    admin gets ``admin`` at the first login, because otherwise a fresh OIDC
    installation locks itself out; the email bootstrap counts only with a verified
    mail claim. The gremium memberships follow the OIDC groups that the upsert has
    just cached. One LOGIN audit entry joins the transaction of the session.
    The caller commits.

    Returns:
        The signed `sid` cookie value and the principal row.

    Raises:
        ForbiddenError: The principal is deactivated or merged into another one.
    """
    token_set = await oidc.exchange_code(settings, code=code, verifier=verifier)
    claims = await oidc.verify_id_token(
        settings, id_token=token_set["id_token"], nonce=nonce
    )
    row = await upsert_principal(db, claims)
    if row.active is False:
        raise ForbiddenError("Account is deactivated.")
    await ensure_admin_for_principal(
        db, settings, row, email_verified=claims.email_verified
    )
    await ensure_member_for_principal(db, row)
    await sync_principal_memberships(db, row)
    now = _now()
    cookie = await sessions.create_principal_session(
        db,
        secret=settings.session_secret,
        principal_id=row.id,
        expires_at=await session_expiry(db, client, now),
        refresh_token=token_set.get("refresh_token"),
        id_token=token_set.get("id_token"),
        client=client,
        now=now,
    )
    await audit_record(
        db,
        actor=row.sub,
        action=AuditAction.LOGIN,
        target_type="principal",
        target_id=str(row.id),
        data={"method": "oidc"},
    )
    return cookie, row
