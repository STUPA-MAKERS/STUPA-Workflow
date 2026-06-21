"""Integration: Authorization-Code ist auch bei NEBENLÄUFIGEM Tausch einmal-verwendbar.

Regression für AUD-003: zwei Token-Requests mit demselben Code+Verifier dürfen nicht
beide ein Token-Paar erhalten. ``exchange_code`` beansprucht die Code-Zeile atomar via
``UPDATE ... WHERE used_at IS NULL RETURNING id`` — der Verlierer bekommt ``invalid_grant``.

Wir simulieren den Race so eng, wie es deterministisch geht: zwei getrennte Sessions
lesen die noch unverbrauchte Zeile (beide sehen ``used_at IS NULL``), erst danach
committen sie nacheinander. Ohne den atomaren Guard würden beide ein Token minten.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth import oauth, oauth_service
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oauth_models import OAuthAuthorizationCode, OAuthToken

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
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def test_concurrent_exchange_only_one_wins(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    # Setup: Principal + frischer Code in einer eigenen, committeten Session.
    async with maker() as setup:
        principal = PrincipalRow(
            sub=f"sub-{uuid.uuid4()}", email="u@example.com", active=True
        )
        setup.add(principal)
        await setup.flush()
        code = await oauth_service.create_authorization_code(
            setup,
            principal_id=principal.id,
            client_id=_CLIENT,
            redirect_uri=_REDIRECT,
            code_challenge=_challenge(_VERIFIER),
            scope="read",
            now=datetime.now(UTC),
            ttl_seconds=300,
            access_ttl_seconds=_ACCESS_TTL,
        )
        await setup.commit()

    now = datetime.now(UTC)
    kw = dict(
        code=code,
        code_verifier=_VERIFIER,
        redirect_uri=_REDIRECT,
        client_id=_CLIENT,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )

    winners = 0
    losers = 0
    # Zwei getrennte Sessions: beide lesen die unverbrauchte Zeile, dann commit nacheinander.
    async with maker() as s1, maker() as s2:
        # Beide sehen used_at IS NULL (klassisches Read-vor-Write-Race).
        for s in (s1, s2):
            pre = (
                await s.execute(
                    select(OAuthAuthorizationCode.used_at).where(
                        OAuthAuthorizationCode.code_hash == oauth.hash_token(code)
                    )
                )
            ).scalar_one()
            assert pre is None

        try:
            await oauth_service.exchange_code(s1, **kw)  # type: ignore[arg-type]
            await s1.commit()
            winners += 1
        except oauth.OAuthError:
            losers += 1

        try:
            await oauth_service.exchange_code(s2, **kw)  # type: ignore[arg-type]
            await s2.commit()
            winners += 1
        except oauth.OAuthError:
            losers += 1

    assert winners == 1, "exactly one exchange may mint a token family"
    assert losers == 1, "the second exchange must be rejected as invalid_grant"

    # Genau EINE Token-Familie existiert in der DB — kein Double-Spend.
    async with maker() as check:
        tokens = (
            await check.execute(select(OAuthToken).where(OAuthToken.client_id == _CLIENT))
        ).scalars().all()
        assert len(tokens) == 1
