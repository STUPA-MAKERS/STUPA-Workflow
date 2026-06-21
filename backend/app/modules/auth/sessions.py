"""Session-/Token-Handling (security.md §1/§2).

Zwei Mechanismen:

- **Principal-Session** (OIDC): serverseitige `auth_session`-Zeile, der Browser hält
  nur die signierte, opake `sid` (HttpOnly+Secure+SameSite=Lax). id/refresh-Token
  bleiben in der DB.
- **Applicant-Session** (Magic-Link): serverseitige `applicant_session`-Zeile; der
  Browser hält — wie bei der Principal-Session — nur eine signierte, opake `sid`
  (HttpOnly-Cookie / Bearer). `application_id`+`scope` liegen serverseitig. Damit ist
  ein Token nicht mehr allein aus `SESSION_SECRET` fälschbar und serverseitig
  widerrufbar (Logout / `revoked_at`). Kein JWT im JS — Cookie ist HttpOnly.
- **OIDC-Transaktion**: signiertes, kurzlebiges Cookie mit `state`/`code_verifier`/
  `nonce` für den Auth-Code+PKCE-Flow (zustandslos, kein Server-Store nötig).

Signaturfehler/Ablauf → `None` (Aufrufer mappt auf 401/410), nie Exception nach außen.
"""

from __future__ import annotations

import secrets
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import ApplicantSession, AuthSession

_APPLICANT_SALT = "applicant-session"
_OIDC_TX_SALT = "oidc-tx"
_OAUTH_TX_SALT = "oauth-tx"
_SID_SALT = "principal-sid"
_SID_BYTES = 32


def _serializer(secret: str, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt=salt)


# --------------------------------------------------------------------------- #
# Applicant-Session (serverseitig, opake sid im signierten Cookie)
# --------------------------------------------------------------------------- #
def _sign_applicant_sid(secret: str, sid: str) -> str:
    return _serializer(secret, _APPLICANT_SALT).dumps(sid)


def _unsign_applicant_sid(secret: str, value: str, max_age: int) -> str | None:
    try:
        sid = _serializer(secret, _APPLICANT_SALT).loads(value, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return str(sid) if isinstance(sid, str) else None


async def create_applicant_session(
    db: AsyncSession,
    *,
    secret: str,
    application_id: Any,
    scope: str,
    expires_at: Any,
) -> str:
    """`applicant_session`-Zeile anlegen; signiertes `sid`-Cookie zurückgeben.

    Spiegelt :func:`create_principal_session`: die opake `sid` ist der einzige Anker —
    ohne existierende Zeile ist kein Zugriff möglich, auch nicht mit `SESSION_SECRET`."""
    sid = secrets.token_urlsafe(_SID_BYTES)
    db.add(
        ApplicantSession(
            sid=sid,
            application_id=application_id,
            scope=scope,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return _sign_applicant_sid(secret, sid)


async def load_applicant_session(
    db: AsyncSession, *, secret: str, cookie_value: str, now: Any, max_age: int
) -> ApplicantSession | None:
    """Cookie → `applicant_session`-Zeile (None bei ungültig/abgelaufen/widerrufen)."""
    sid = _unsign_applicant_sid(secret, cookie_value, max_age)
    if sid is None:
        return None
    row = (
        await db.execute(select(ApplicantSession).where(ApplicantSession.sid == sid))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    return row


async def delete_applicant_session(
    db: AsyncSession, *, secret: str, cookie_value: str, max_age: int
) -> ApplicantSession | None:
    """Logout: Applicant-Session-Zeile löschen (idempotent). None, wenn nichts traf."""
    sid = _unsign_applicant_sid(secret, cookie_value, max_age)
    if sid is None:
        return None
    row = (
        await db.execute(select(ApplicantSession).where(ApplicantSession.sid == sid))
    ).scalar_one_or_none()
    if row is None:
        return None
    await db.delete(row)
    await db.flush()
    return row


async def revoke_applicant_sessions(
    db: AsyncSession, application_id: Any, *, now: Any
) -> None:
    """Kill-Switch: alle aktiven Applicant-Sessions eines Antrags widerrufen
    (`revoked_at = now`). Idempotent; bei Anonymisierung/Löschung aufgerufen."""
    await db.execute(
        update(ApplicantSession)
        .where(
            ApplicantSession.application_id == application_id,
            ApplicantSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


# --------------------------------------------------------------------------- #
# OIDC-Transaktions-Cookie (state + PKCE-verifier + nonce)
# --------------------------------------------------------------------------- #
def issue_oidc_tx(secret: str, state: str, verifier: str, nonce: str) -> str:
    return _serializer(secret, _OIDC_TX_SALT).dumps(
        {"state": state, "verifier": verifier, "nonce": nonce}
    )


def load_oidc_tx(secret: str, value: str, max_age: int) -> dict[str, str] | None:
    try:
        data = _serializer(secret, _OIDC_TX_SALT).loads(value, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or not {"state", "verifier", "nonce"} <= set(data):
        return None
    return {k: str(data[k]) for k in ("state", "verifier", "nonce")}


# --------------------------------------------------------------------------- #
# OAuth-AS-Transaktions-Cookie (MCP-Login: authorize-Request über den OIDC-Hop)
# --------------------------------------------------------------------------- #
_OAUTH_TX_FIELDS = ("client_id", "redirect_uri", "code_challenge", "scope", "state")


def issue_oauth_tx(secret: str, data: dict[str, str]) -> str:
    """Authorize-Request (client_id/redirect_uri/challenge/scope/state) signiert ablegen."""
    return _serializer(secret, _OAUTH_TX_SALT).dumps(
        {k: data.get(k, "") for k in _OAUTH_TX_FIELDS}
    )


def load_oauth_tx(secret: str, value: str, max_age: int) -> dict[str, str] | None:
    try:
        data = _serializer(secret, _OAUTH_TX_SALT).loads(value, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or not {
        "client_id",
        "redirect_uri",
        "code_challenge",
    } <= set(data):
        return None
    return {k: str(data.get(k, "")) for k in _OAUTH_TX_FIELDS}


# --------------------------------------------------------------------------- #
# Principal-Session (serverseitig, opake sid im signierten Cookie)
# --------------------------------------------------------------------------- #
def _sign_sid(secret: str, sid: str) -> str:
    return _serializer(secret, _SID_SALT).dumps(sid)


def _unsign_sid(secret: str, value: str, max_age: int) -> str | None:
    try:
        sid = _serializer(secret, _SID_SALT).loads(value, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    return str(sid) if isinstance(sid, str) else None


async def create_principal_session(
    db: AsyncSession,
    *,
    secret: str,
    principal_id: Any,
    expires_at: Any,
    refresh_token: str | None,
    id_token: str | None,
) -> str:
    """`auth_session`-Zeile anlegen; signiertes `sid`-Cookie zurückgeben."""
    sid = secrets.token_urlsafe(_SID_BYTES)
    db.add(
        AuthSession(
            sid=sid,
            principal_id=principal_id,
            expires_at=expires_at,
            refresh_token=refresh_token,
            id_token=id_token,
        )
    )
    await db.flush()
    return _sign_sid(secret, sid)


async def load_principal_session(
    db: AsyncSession, *, secret: str, cookie_value: str, now: Any, max_age: int
) -> AuthSession | None:
    """Cookie → `auth_session`-Zeile (None bei ungültig/abgelaufen)."""
    sid = _unsign_sid(secret, cookie_value, max_age)
    if sid is None:
        return None
    row = (
        await db.execute(select(AuthSession).where(AuthSession.sid == sid))
    ).scalar_one_or_none()
    if row is None or row.expires_at <= now:
        return None
    return row


async def delete_principal_session(
    db: AsyncSession, *, secret: str, cookie_value: str, max_age: int
) -> AuthSession | None:
    """Session-Zeile löschen (Logout). Gibt die gelöschte Zeile (id_token-Hint) zurück."""
    sid = _unsign_sid(secret, cookie_value, max_age)
    if sid is None:
        return None
    row = (
        await db.execute(select(AuthSession).where(AuthSession.sid == sid))
    ).scalar_one_or_none()
    if row is None:
        return None
    await db.delete(row)
    await db.flush()
    return row
