"""Integration: OAuth2-AS-Service gegen echtes Postgres — Code/Exchange/Refresh/Resolve.

Deckt den sicherheitskritischen Token-Pfad ab: PKCE-Bindung, Einmal-Code, Refresh-
Rotation, Ablauf/Widerruf. Der Browser-/OIDC-Hop (authorize→finish) ist hier nicht
abgebildet (bräuchte Keycloak); die Endpunkt-Validierung ist separat unit-getestet.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth import oauth, oauth_service
from app.modules.auth.models import Principal as PrincipalRow

pytestmark = pytest.mark.integration

_CLIENT = "antragsplattform-mcp"
_REDIRECT = "http://127.0.0.1:7777/callback"
_VERIFIER = "v" * 64
_ACCESS_TTL = 3600
_REFRESH_TTL = 86400


def _challenge(verifier: str) -> str:
    d = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(d).rstrip(b"=").decode("ascii")


@pytest.fixture
async def session(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[AsyncSession]:
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()


async def _principal(session: AsyncSession) -> uuid.UUID:
    row = PrincipalRow(sub=f"sub-{uuid.uuid4()}", email="u@example.com", active=True)
    session.add(row)
    await session.flush()
    return row.id


async def _mint_code(
    session: AsyncSession,
    pid: uuid.UUID,
    *,
    scope: str = "read",
    access_ttl_seconds: int | None = _ACCESS_TTL,
) -> str:
    return await oauth_service.create_authorization_code(
        session,
        principal_id=pid,
        client_id=_CLIENT,
        redirect_uri=_REDIRECT,
        code_challenge=_challenge(_VERIFIER),
        scope=scope,
        now=datetime.now(UTC),
        ttl_seconds=300,
        access_ttl_seconds=access_ttl_seconds,
    )


async def test_full_code_exchange_and_resolve(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid, scope="read votes:write")
    now = datetime.now(UTC)
    issued = await oauth_service.exchange_code(
        session,
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    assert oauth.is_access_token(issued.access_token)
    assert issued.scope == "read votes:write"
    resolved = await oauth_service.resolve_access_token(
        session, token=issued.access_token, now=now
    )
    assert resolved == (pid, "read votes:write")


async def test_pkce_mismatch_rejected(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid)
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            session,
            code=code,
            code_verifier="wrong-verifier",
            redirect_uri=_REDIRECT,
            client_id=_CLIENT,
            now=datetime.now(UTC),
            access_ttl=_ACCESS_TTL,
            refresh_ttl=_REFRESH_TTL,
        )
    assert exc.value.error == "invalid_grant"


async def test_redirect_uri_mismatch_rejected(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid)
    with pytest.raises(oauth.OAuthError):
        await oauth_service.exchange_code(
            session,
            code=code,
            code_verifier=_VERIFIER,
            redirect_uri="http://127.0.0.1:9999/other",
            client_id=_CLIENT,
            now=datetime.now(UTC),
            access_ttl=_ACCESS_TTL,
            refresh_ttl=_REFRESH_TTL,
        )


async def test_code_is_single_use(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid)
    kw = dict(
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=datetime.now(UTC),
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    await oauth_service.exchange_code(session, **kw)  # type: ignore[arg-type]
    with pytest.raises(oauth.OAuthError):
        await oauth_service.exchange_code(session, **kw)  # type: ignore[arg-type]


async def test_refresh_rotates_and_revokes_old(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid)
    now = datetime.now(UTC)
    first = await oauth_service.exchange_code(
        session,
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    second = await oauth_service.refresh_tokens(
        session,
        refresh_token=first.refresh_token,
        client_id=_CLIENT,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    assert second.access_token != first.access_token
    # alter Access-Token ist nach Rotation widerrufen
    assert await oauth_service.resolve_access_token(
        session, token=first.access_token, now=now
    ) is None
    # alter Refresh-Token kann nicht erneut verwendet werden
    with pytest.raises(oauth.OAuthError):
        await oauth_service.refresh_tokens(
            session,
            refresh_token=first.refresh_token,
            client_id=_CLIENT,
            now=now,
            access_ttl=_ACCESS_TTL,
            refresh_ttl=_REFRESH_TTL,
        )


async def test_expired_access_token_not_resolved(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid)
    now = datetime.now(UTC)
    issued = await oauth_service.exchange_code(
        session,
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    later = now + timedelta(seconds=_ACCESS_TTL + 1)
    assert await oauth_service.resolve_access_token(
        session, token=issued.access_token, now=later
    ) is None


async def test_never_expiring_token_resolves_far_future(session: AsyncSession) -> None:
    pid = await _principal(session)
    code = await _mint_code(session, pid, access_ttl_seconds=None)  # »läuft nie ab«
    now = datetime.now(UTC)
    issued = await oauth_service.exchange_code(
        session,
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )
    assert issued.expires_in is None
    # Auch Jahre später noch gültig (nur Widerruf beendet es).
    far = now + timedelta(days=3650)
    resolved = await oauth_service.resolve_access_token(
        session, token=issued.access_token, now=far
    )
    assert resolved is not None and resolved[0] == pid
