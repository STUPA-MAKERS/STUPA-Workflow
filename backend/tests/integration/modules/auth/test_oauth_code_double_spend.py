"""Integration: the authorization code stays single use under a CONCURRENT exchange.

Regression for AUD-003. Two token requests with the same code and verifier must not both
get a token pair. `exchange_code` claims the code row atomically with
`UPDATE ... WHERE used_at IS NULL RETURNING id`. The loser gets `invalid_grant`.

The test makes the race as tight as a deterministic test allows. Two separate sessions
read the row while it is still unused, so both see `used_at IS NULL`. Only then do they
commit one after the other. Without the atomic guard both would mint a token.
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
    async with maker() as s1, maker() as s2:
        # Both sessions see used_at IS NULL. This is the classic read-before-write race.
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

    # There is no double spend. Exactly one token family exists in the database.
    async with maker() as check:
        tokens = (
            await check.execute(select(OAuthToken).where(OAuthToken.client_id == _CLIENT))
        ).scalars().all()
        assert len(tokens) == 1
