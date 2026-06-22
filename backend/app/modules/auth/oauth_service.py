"""OAuth2-AS-Service: Authorization-Code minten, gegen Token tauschen, Token rotieren.

I/O-Schicht auf :mod:`app.modules.auth.oauth_models`; die reine Logik (Scopes, PKCE,
Hashing) liegt in :mod:`app.modules.auth.oauth`. Codes sind einmal-verwendbar (``used_at``
atomar gesetzt), Refresh rotiert (alte Zeile ``revoked_at``). Commit macht der Aufrufer.
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
    """Authorization-Code anlegen (gehasht) und Klartext zurückgeben.

    ``access_ttl_seconds`` ist die im Consent gewählte Token-Lebensdauer (``None`` =
    läuft nie ab); sie wird beim Token-Tausch angewendet."""
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
    """Frisch ausgestelltes Token-Paar (Klartext nur hier, danach nie wieder)."""

    __slots__ = ("access_token", "refresh_token", "scope", "expires_in")

    def __init__(
        self, access_token: str, refresh_token: str, scope: str, expires_in: int | None
    ) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.scope = scope
        self.expires_in = expires_in  # None = läuft nie ab


def _expiry(now: datetime, ttl: int | None) -> datetime | None:
    """TTL (Sekunden) → Ablaufzeitpunkt; ``None`` → ``None`` (nie ablaufend)."""
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
    """Authorization-Code → Token-Paar. PKCE + Bindung an client/redirect geprüft.

    Einmal-Verwendung (RFC 6749 §4.1.2): das Einlösen erfolgt über ein atomares
    ``UPDATE ... WHERE id=? AND used_at IS NULL RETURNING id`` (spiegelt den
    Magic-Link-Pfad). Unter ``READ COMMITTED`` serialisiert die DB konkurrierende
    Einlösungen — nur genau eine beansprucht die Zeile, jede weitere bekommt 0 Zeilen
    und damit ``invalid_grant``. Validierung (Ablauf/Bindung/PKCE) läuft vorab, damit
    ein fehlgeschlagener Request den Code nicht verbrennt. Fehler →
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
    # Atomares Beanspruchen: nur die erste nebenläufige Einlösung gewinnt. 0 Zeilen →
    # der Code wurde zwischen SELECT und UPDATE bereits verbraucht (Double-Spend-Schutz).
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
    # Die im Consent gewählte Lebensdauer (``access_ttl_seconds``) ist maßgeblich —
    # ``None`` bedeutet »läuft nie ab« (NICHT Default). Refresh läuft dann ebenfalls nie ab.
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
    """Refresh-Token → neues Paar; altes Token wird widerrufen (Rotation).

    Rotation läuft über ein atomares ``UPDATE ... WHERE id=? AND revoked_at IS NULL
    RETURNING id`` — bei nebenläufiger Einlösung gewinnt nur die erste, die zweite
    sieht 0 Zeilen. Wird ein bereits rotiertes (widerrufenes) Token erneut vorgelegt,
    deutet das auf Diebstahl/Replay hin: dann wird die gesamte noch aktive Token-Familie
    dieses Principals + Clients kaskadierend widerrufen (RFC 6819 §5.2.2.3), was eine
    Neu-Authentisierung erzwingt.
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
        # Replay eines bereits rotierten Tokens → Familie zwangsweise widerrufen.
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
    # Aktiv-Prüfung vor der Rotation: ein deaktivierter Principal darf kein frisches
    # Token-Paar mehr erhalten (spiegelt die Ablehnung in ``deps`` für Access-Tokens).
    principal = (
        await db.execute(select(Principal).where(Principal.id == row.principal_id))
    ).scalar_one_or_none()
    if principal is None or principal.active is False:
        raise oauth.OAuthError("invalid_grant", "principal inactive")
    # Atomares Rotieren: nur die erste nebenläufige Einlösung gewinnt. 0 Zeilen →
    # das Token wurde zwischen SELECT und UPDATE bereits rotiert (Race-Schutz).
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
    # Gewählte Lebensdauer über die Rotation hinweg beibehalten (``None`` = nie).
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
    """Gültiges Access-Token → ``(principal_id, scope)`` oder ``None``."""
    row = (
        await db.execute(
            select(OAuthToken).where(
                OAuthToken.access_token_hash == oauth.hash_token(token)
            )
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    # ``access_expires_at is None`` → läuft nie ab (nur Widerruf beendet das Token).
    if row.access_expires_at is not None and row.access_expires_at <= now:
        return None
    return row.principal_id, row.scope
