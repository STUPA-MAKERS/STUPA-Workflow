"""Session/token handling.

Principal session (OIDC) and applicant session (magic link) are server-side
rows; the browser holds only a signed, opaque `sid` in an HttpOnly cookie.
Tokens are thus not forgeable from `SESSION_SECRET` alone (a row must exist)
and are server-side revocable (logout / `revoked_at`). The OIDC transaction is
a signed short-lived cookie with `state`/`code_verifier`/`nonce` for the
auth-code+PKCE flow (stateless, no server store).

Signature errors/expiry return `None` (caller maps to 401/410), never an
exception to the outside.
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


# --- applicant session (server-side, opaque sid in a signed cookie) ---
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
    """Create an `applicant_session` row; return the signed `sid` cookie.

    Mirrors :func:`create_principal_session`: the opaque `sid` is the only
    anchor — without an existing row there is no access, even with
    `SESSION_SECRET`."""
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
    """Resolve a cookie to its `applicant_session` row (None if invalid/expired/revoked)."""
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
    """Logout: delete the applicant-session row (idempotent). None if nothing matched."""
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
    """Kill switch: revoke all active applicant sessions of an application
    (`revoked_at = now`). Idempotent; called on anonymization/deletion."""
    await db.execute(
        update(ApplicantSession)
        .where(
            ApplicantSession.application_id == application_id,
            ApplicantSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


# --- OIDC transaction cookie (state + PKCE verifier + nonce) ---
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


# --- OAuth AS transaction cookie (MCP login: authorize request across the OIDC hop) ---
_OAUTH_TX_FIELDS = ("client_id", "redirect_uri", "code_challenge", "scope", "state")


def issue_oauth_tx(secret: str, data: dict[str, str]) -> str:
    """Sign and store the authorize request (client_id/redirect_uri/challenge/scope/state)."""
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


# --- principal session (server-side, opaque sid in a signed cookie) ---
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
    """Create an `auth_session` row; return the signed `sid` cookie."""
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
    """Resolve a cookie to its `auth_session` row (None if invalid/expired)."""
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
    """Delete the session row (logout). Returns the deleted row (id_token hint)."""
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
