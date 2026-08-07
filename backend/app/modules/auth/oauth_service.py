"""OAuth2 authorization-server service: mint codes, exchange them, rotate tokens.

This module is the I/O layer over `app.modules.auth.oauth_models`. The pure logic for
scopes, PKCE and hashing lives in `app.modules.auth.oauth`. A code is single-use, because
the exchange sets `used_at` atomically. A refresh rotates the pair and sets `revoked_at` on
the old row. The caller commits.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import oauth
from app.modules.auth.models import Principal
from app.modules.auth.oauth_models import OAuthAuthorizationCode, OAuthToken


async def create_authorization_code(
    db: AsyncSession,
    *,
    principal_id: UUID,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    scope: str,
    now: datetime,
    ttl_seconds: int,
    access_ttl_seconds: int | None,
) -> str:
    """Create a hashed authorization code and return the plaintext.

    The `access_ttl_seconds` value is the token lifetime chosen in the consent. `None`
    means that the token never expires. The token exchange applies this value.
    """
    code = oauth.generate_access_token().replace(oauth._ACCESS_PREFIX, "apac_", 1)
    db.add(
        OAuthAuthorizationCode(
            code_hash=oauth.hash_token(code),
            principal_id=principal_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            access_ttl_seconds=access_ttl_seconds,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    await db.flush()
    return code


class IssuedTokens:
    """A fresh token pair.

    The plaintext exists only in this object and never again.
    """

    __slots__ = ("access_token", "refresh_token", "scope", "expires_in")

    def __init__(
        self, access_token: str, refresh_token: str, scope: str, expires_in: int | None
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.scope = scope
        self.expires_in = expires_in  # None means the token never expires


def _expiry(now: datetime, ttl: int | None) -> datetime | None:
    """Map a TTL in seconds to an expiry timestamp.

    A `None` TTL stays `None` and means that the token never expires.
    """
    return None if ttl is None else now + timedelta(seconds=ttl)


async def _issue_tokens(
    db: AsyncSession,
    *,
    principal_id: UUID,
    client_id: str,
    scope: str,
    now: datetime,
    access_ttl: int | None,
    refresh_ttl: int | None,
) -> IssuedTokens:
    access = oauth.generate_access_token()
    refresh = oauth.generate_refresh_token()
    db.add(
        OAuthToken(
            principal_id=principal_id,
            client_id=client_id,
            access_token_hash=oauth.hash_token(access),
            refresh_token_hash=oauth.hash_token(refresh),
            scope=scope,
            access_ttl_seconds=access_ttl,
            access_expires_at=_expiry(now, access_ttl),
            refresh_expires_at=_expiry(now, refresh_ttl),
        )
    )
    await db.flush()
    return IssuedTokens(access, refresh, scope, access_ttl)


async def exchange_code(
    db: AsyncSession,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    client_id: str,
    now: datetime,
    access_ttl: int,
    refresh_ttl: int,
) -> IssuedTokens:
    """Exchange an authorization code for a token pair.

    The function checks the PKCE verifier and the binding to the client and the redirect
    URI. The code is single-use (RFC 6749). The redemption is an atomic
    `UPDATE ... WHERE id=? AND used_at IS NULL RETURNING id`. Under READ COMMITTED the
    database serializes concurrent redemptions. Exactly one caller claims the row. The
    other callers get `invalid_grant`. The checks of expiry, binding and PKCE run first, so
    a failed request does not burn the code.

    Raises:
        OAuthError: The code is unknown, used, expired, or the binding or the PKCE check
            fails. The error code is `invalid_grant`.
    """
    row = (
        await db.execute(
            select(OAuthAuthorizationCode).where(
                OAuthAuthorizationCode.code_hash == oauth.hash_token(code)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        raise oauth.OAuthError("invalid_grant", "code invalid or already used")
    if row.expires_at <= now:
        raise oauth.OAuthError("invalid_grant", "code expired")
    if row.client_id != client_id or row.redirect_uri != redirect_uri:
        raise oauth.OAuthError("invalid_grant", "client/redirect mismatch")
    if not oauth.verify_pkce_s256(code_verifier, row.code_challenge):
        raise oauth.OAuthError("invalid_grant", "PKCE verification failed")
    # Atomic claim: only the first concurrent redemption wins. Zero rows mean that another
    # caller consumed the code between the SELECT and the UPDATE (double-spend guard).
    claimed = (
        await db.execute(
            update(OAuthAuthorizationCode)
            .where(
                OAuthAuthorizationCode.id == row.id,
                OAuthAuthorizationCode.used_at.is_(None),
            )
            .values(used_at=now)
            .returning(OAuthAuthorizationCode.id)
        )
    ).scalar_one_or_none()
    if claimed is None:
        raise oauth.OAuthError("invalid_grant", "code invalid or already used")
    # The lifetime chosen in the consent (`access_ttl_seconds`) wins. `None` means that
    # the token never expires. It does not mean the default. The refresh token then never
    # expires either.
    consent_ttl = row.access_ttl_seconds
    return await _issue_tokens(
        db,
        principal_id=row.principal_id,
        client_id=client_id,
        scope=row.scope,
        now=now,
        access_ttl=consent_ttl,
        refresh_ttl=None if consent_ttl is None else refresh_ttl,
    )


async def refresh_tokens(
    db: AsyncSession,
    *,
    refresh_token: str,
    client_id: str,
    now: datetime,
    access_ttl: int,
    refresh_ttl: int,
) -> IssuedTokens:
    """Exchange a refresh token for a new pair and revoke the old one.

    The rotation is an atomic `UPDATE ... WHERE id=? AND revoked_at IS NULL RETURNING id`.
    Only the first concurrent redemption wins. An already-rotated token points to a theft
    or a replay. The service then revokes the whole still-active token family of this
    principal and client (RFC 6819). The client must authenticate again.

    Raises:
        OAuthError: The refresh token is invalid, revoked or expired, the client does not
            match, or the principal is inactive. The error code is `invalid_grant`.
    """
    row = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.refresh_token_hash == oauth.hash_token(refresh_token)
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise oauth.OAuthError("invalid_grant", "refresh token invalid or revoked")
    if row.revoked_at is not None:
        # A replay of an already-rotated token forces a revocation of the whole family.
        await db.execute(
            update(OAuthToken)
            .where(
                OAuthToken.principal_id == row.principal_id,
                OAuthToken.client_id == row.client_id,
                OAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        raise oauth.OAuthError("invalid_grant", "refresh token invalid or revoked")
    if row.client_id != client_id:
        raise oauth.OAuthError("invalid_grant", "client mismatch")
    if row.refresh_expires_at is not None and row.refresh_expires_at <= now:
        raise oauth.OAuthError("invalid_grant", "refresh token expired")
    # Check `active` before the rotation. A deactivated principal must not get a fresh
    # token pair. This mirrors the access-token rejection in `deps`.
    principal = (
        await db.execute(select(Principal).where(Principal.id == row.principal_id))
    ).scalar_one_or_none()
    if principal is None or principal.active is False:
        raise oauth.OAuthError("invalid_grant", "principal inactive")
    # Atomic rotation: only the first concurrent redemption wins. Zero rows mean that
    # another caller rotated the token between the SELECT and the UPDATE.
    rotated = (
        await db.execute(
            update(OAuthToken)
            .where(
                OAuthToken.id == row.id,
                OAuthToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(OAuthToken.id)
        )
    ).scalar_one_or_none()
    if rotated is None:
        raise oauth.OAuthError("invalid_grant", "refresh token invalid or revoked")
    # Keep the chosen lifetime across the rotation. `None` means never.
    keep_access = row.access_ttl_seconds
    return await _issue_tokens(
        db,
        principal_id=row.principal_id,
        client_id=client_id,
        scope=row.scope,
        now=now,
        access_ttl=keep_access,
        refresh_ttl=None if keep_access is None else refresh_ttl,
    )


async def load_grant(db: AsyncSession, grant_id: str | UUID) -> OAuthToken | None:
    """Load one grant row by id, whoever owns it. The caller authorizes the access."""
    return (
        await db.execute(select(OAuthToken).where(OAuthToken.id == grant_id))
    ).scalar_one_or_none()


def revoke_grant(row: OAuthToken, now: datetime) -> bool:
    """Revoke one grant, so that its access and refresh token die at once.

    The caller commits.

    Returns:
        True when this call revoked the grant, False when it was revoked before.
    """
    if row.revoked_at is not None:
        return False
    row.revoked_at = now
    return True


async def revoke_all_grants(db: AsyncSession, *, principal_id: UUID, now: datetime) -> int:
    """Revoke every grant of one principal. The caller commits.

    Returns:
        The number of revoked grants.
    """
    rows = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.principal_id == principal_id, OAuthToken.revoked_at.is_(None)
            )
        )
    ).scalars().all()
    for row in rows:
        revoke_grant(row, now)
    return len(rows)


async def resolve_access_token(
    db: AsyncSession, *, token: str, now: datetime
) -> tuple[UUID, str] | None:
    """Resolve a valid access token to `(principal_id, scope)`, or return `None`."""
    row = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.access_token_hash == oauth.hash_token(token)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    # `access_expires_at is None` means the token never expires. Only a revocation ends it.
    if row.access_expires_at is not None and row.access_expires_at <= now:
        return None
    return row.principal_id, row.scope
