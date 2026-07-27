"""Integration: the OIDC callback commits the principal and the auth_session row.

The test reproduces the T-10 bug. Without `await db.commit()` in the callback handler,
the DB rolls back the fresh principal and the `auth_session` row when the request
session closes. A later `GET /auth/me` with the session cookie then returns 401 instead
of 200.

The test needs real Postgres (`gen_random_uuid`, jsonb groups) and an RS256-signed
id_token (respx, as in T-10). It also needs the real ASGI request cycle through
`get_session`, which **never** commits by itself. Only this setup shows the missing
persistence in the router.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import get_session
from app.main import create_app
from app.modules.auth import oidc, sessions
from app.settings import get_settings, load_settings

ISSUER = "https://kc.example/realms/app"
CLIENT_ID = "antrag"
CERTS = f"{ISSUER}/protocol/openid-connect/certs"
TOKEN = f"{ISSUER}/protocol/openid-connect/token"

pytestmark = pytest.mark.integration

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "k1"


def _jwk() -> dict[str, object]:
    pub = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    pub["kid"] = _KID
    return pub


def _id_token(nonce: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(  # type: ignore[arg-type]
        {
            "sub": "user-cb-1",
            "aud": CLIENT_ID,
            "iss": ISSUER,
            "iat": now,
            "exp": now + timedelta(hours=1),
            "email": "cb@x.de",
            "name": "Callback User",
            "nonce": nonce,
        },
        _KEY,
        algorithm="RS256",
        headers={"kid": _KID},
    )


async def test_callback_persists_principal_then_me_returns_200(
    migrated: tuple[str, str],
) -> None:
    """The callback creates the principal and the session.

    A `/auth/me` call with the cookie then returns 200, not 401.
    """
    _, async_url = migrated
    settings = load_settings(
        database_url=async_url,
        session_secret="session-secret-0123",
        magic_link_secret="magic-link-secret-0",
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret="client-secret-01234",
        oidc_redirect_url="https://antrag.example/api/auth/callback",
        cookie_secure=False,  # http://testserver would not send a Secure cookie back
    )
    oidc._jwks_cache.clear()

    engine = create_async_engine(async_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    async def _request_session() -> AsyncIterator[object]:
        """Behave like `app.db.get_session`: yield and close, with **no** auto commit."""
        db = sessionmaker()
        try:
            yield db
        finally:
            await db.close()

    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = _request_session

    state, verifier, nonce = "state-cb-1", "verifier-cb-1", "nonce-cb-1"
    tx = sessions.issue_oidc_tx(settings.session_secret, state, verifier, nonce)

    transport = httpx.ASGITransport(app=app)
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock.post(TOKEN).mock(
                return_value=httpx.Response(
                    200, json={"id_token": _id_token(nonce), "refresh_token": "rt"}
                )
            )
            mock.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
            mock.route(host="testserver").pass_through()  # pass ASGI requests through
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
                follow_redirects=False,
            ) as client:
                client.cookies.set(settings.oidc_tx_cookie_name, tx)
                callback = await client.get(
                    "/api/auth/callback", params={"code": "auth-code", "state": state}
                )
                assert callback.status_code == 307, callback.text
                assert settings.session_cookie_name in callback.cookies
                me = await client.get("/api/auth/me")
    finally:
        await engine.dispose()

    assert me.status_code == 200, me.text  # without the commit in the callback: 401
    body = me.json()
    assert body["sub"] == "user-cb-1"
    assert body["email"] == "cb@x.de"
