"""OAuth2-AS-Service: Authorization-Code minten, gegen Token tauschen, Token rotieren.

I/O-Schicht auf :mod:`app.modules.auth.oauth_models`; die reine Logik (Scopes, PKCE,
Hashing) liegt in :mod:`app.modules.auth.oauth`. Codes sind einmal-verwendbar (``used_at``
atomar gesetzt), Refresh rotiert (alte Zeile ``revoked_at``). Commit macht der Aufrufer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import oauth
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
) -> str:
    """Authorization-Code anlegen (gehasht) und Klartext zurückgeben."""
    code = oauth.generate_access_token().replace(oauth._ACCESS_PREFIX, "apac_", 1)
    db.add(
        OAuthAuthorizationCode(
            code_hash=oauth.hash_token(code),
            principal_id=principal_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    await db.flush()
    return code


class IssuedTokens:
    """Frisch ausgestelltes Token-Paar (Klartext nur hier, danach nie wieder)."""

    __slots__ = ("access_token", "refresh_token", "scope", "expires_in")

    def __init__(
        self, access_token: str, refresh_token: str, scope: str, expires_in: int
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.scope = scope
        self.expires_in = expires_in


async def _issue_tokens(
    db: AsyncSession,
    *,
    principal_id: UUID,
    client_id: str,
    scope: str,
    now: datetime,
    access_ttl: int,
    refresh_ttl: int,
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
            access_expires_at=now + timedelta(seconds=access_ttl),
            refresh_expires_at=now + timedelta(seconds=refresh_ttl),
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
    """Authorization-Code → Token-Paar. PKCE + Bindung an client/redirect geprüft.

    Einmal-Verwendung: ``used_at`` wird atomar gesetzt (``WHERE used_at IS NULL``-Race
    über die folgende Prüfung hinaus durch die Transaktion abgedeckt). Fehler →
    ``OAuthError('invalid_grant')``.
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
    row.used_at = now
    return await _issue_tokens(
        db,
        principal_id=row.principal_id,
        client_id=client_id,
        scope=row.scope,
        now=now,
        access_ttl=access_ttl,
        refresh_ttl=refresh_ttl,
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
    """Refresh-Token → neues Paar; altes Token wird widerrufen (Rotation)."""
    row = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.refresh_token_hash == oauth.hash_token(refresh_token)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        raise oauth.OAuthError("invalid_grant", "refresh token invalid or revoked")
    if row.client_id != client_id:
        raise oauth.OAuthError("invalid_grant", "client mismatch")
    if row.refresh_expires_at is not None and row.refresh_expires_at <= now:
        raise oauth.OAuthError("invalid_grant", "refresh token expired")
    row.revoked_at = now
    return await _issue_tokens(
        db,
        principal_id=row.principal_id,
        client_id=client_id,
        scope=row.scope,
        now=now,
        access_ttl=access_ttl,
        refresh_ttl=refresh_ttl,
    )


async def resolve_access_token(
    db: AsyncSession, *, token: str, now: datetime
) -> tuple[UUID, str] | None:
    """Gültiges Access-Token → ``(principal_id, scope)`` oder ``None``."""
    row = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.access_token_hash == oauth.hash_token(token)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.access_expires_at <= now:
        return None
    return row.principal_id, row.scope
