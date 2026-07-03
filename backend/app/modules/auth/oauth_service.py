"""OAuth2 AS service: mint authorization codes, exchange for tokens, rotate tokens.

I/O layer over :mod:`app.modules.auth.oauth_models`; the pure logic (scopes,
PKCE, hashing) lives in :mod:`app.modules.auth.oauth`. Codes are single-use
(``used_at`` set atomically); refresh rotates (old row ``revoked_at``). The
caller commits.
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
    """Create an authorization code (hashed) and return the plaintext.

    ``access_ttl_seconds`` is the token lifetime chosen in the consent
    (``None`` = never expires); it is applied at token exchange."""
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
    """Freshly issued token pair (plaintext exists only here, never again)."""

    __slots__ = ("access_token", "refresh_token", "scope", "expires_in")

    def __init__(
        self, access_token: str, refresh_token: str, scope: str, expires_in: int | None
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.scope = scope
        self.expires_in = expires_in  # None = never expires


def _expiry(now: datetime, ttl: int | None) -> datetime | None:
    """Map a TTL in seconds to an expiry timestamp; ``None`` stays ``None`` (never expires)."""
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
    """Exchange an authorization code for a token pair (PKCE + client/redirect binding checked).

    Single-use (RFC 6749): redemption is an atomic ``UPDATE ... WHERE id=? AND
    used_at IS NULL RETURNING id``. Under READ COMMITTED the DB serializes
    concurrent redemptions — exactly one claims the row, the rest get
    ``invalid_grant``. Validation (expiry/binding/PKCE) runs first so a failed
    request does not burn the code.
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
    # Atomic claim: only the first concurrent redemption wins. 0 rows means the
    # code was consumed between SELECT and UPDATE (double-spend protection).
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
    # The consent-chosen lifetime (``access_ttl_seconds``) is authoritative —
    # ``None`` means "never expires" (NOT default); refresh then never expires either.
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
    """Exchange a refresh token for a new pair; the old token is revoked (rotation).

    Rotation is an atomic ``UPDATE ... WHERE id=? AND revoked_at IS NULL
    RETURNING id`` — only the first concurrent redemption wins. Presenting an
    already-rotated token indicates theft/replay: the entire still-active token
    family of this principal+client is cascade-revoked (RFC 6819), forcing
    re-authentication.
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
        # Replay of an already-rotated token -> force-revoke the family.
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
    # Active check before rotation: a deactivated principal must not receive a
    # fresh token pair (mirrors the access-token rejection in ``deps``).
    principal = (
        await db.execute(select(Principal).where(Principal.id == row.principal_id))
    ).scalar_one_or_none()
    if principal is None or principal.active is False:
        raise oauth.OAuthError("invalid_grant", "principal inactive")
    # Atomic rotation: only the first concurrent redemption wins. 0 rows means
    # the token was rotated between SELECT and UPDATE (race protection).
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
    # Keep the chosen lifetime across the rotation (``None`` = never).
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


async def resolve_access_token(
    db: AsyncSession, *, token: str, now: datetime
) -> tuple[UUID, str] | None:
    """Resolve a valid access token to ``(principal_id, scope)``, or ``None``."""
    row = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.access_token_hash == oauth.hash_token(token)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    # ``access_expires_at is None`` -> never expires (only revocation ends the token).
    if row.access_expires_at is not None and row.access_expires_at <= now:
        return None
    return row.principal_id, row.scope
