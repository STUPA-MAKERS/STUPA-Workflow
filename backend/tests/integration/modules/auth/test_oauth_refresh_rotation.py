"""Integration: refresh-token rotation is atomic and detects reuse.

Regression for AUD-020:

1. CONCURRENT rotation. Two requests with the same refresh token must not both get a
   new pair. `refresh_tokens` rotates atomically with
   `UPDATE ... WHERE id=? AND revoked_at IS NULL RETURNING id`. The loser gets
   `invalid_grant` and the token family does NOT split.

2. REUSE DETECTION (RFC 6819 §5.2.2.3). A caller can present a rotated and therefore
   revoked refresh token again. The server then revokes the whole active token family of
   the principal and the client. This forces the client to authenticate again.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth import oauth, oauth_service
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.oauth_models import OAuthToken

pytestmark = pytest.mark.integration

_ACCESS_TTL = 3600
_REFRESH_TTL = 86400


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _seed_principal_with_token(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, str, str]:
    """Create an active principal and a fresh token family.

    The `client_id` is unique per test. This keeps the client-scoped checks of other
    test files free of these rows.

    Returns:
        The principal id, the client id and the refresh token.
    """
    client_id = f"mcp-{uuid.uuid4()}"
    async with maker() as setup:
        principal = PrincipalRow(
            sub=f"sub-{uuid.uuid4()}", email="u@example.com", active=True
        )
        setup.add(principal)
        await setup.flush()
        issued = await oauth_service._issue_tokens(
            setup,
            principal_id=principal.id,
            client_id=client_id,
            scope="read",
            now=datetime.now(UTC),
            access_ttl=_ACCESS_TTL,
            refresh_ttl=_REFRESH_TTL,
        )
        await setup.commit()
        return principal.id, client_id, issued.refresh_token


def _kw(refresh: str, client_id: str, now: datetime) -> dict[str, object]:
    return dict(
        refresh_token=refresh,
        client_id=client_id,
        now=now,
        access_ttl=_ACCESS_TTL,
        refresh_ttl=_REFRESH_TTL,
    )


async def test_concurrent_refresh_only_one_wins(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    principal_id, client_id, refresh = await _seed_principal_with_token(maker)
    now = datetime.now(UTC)

    winners = 0
    losers = 0
    # Both sessions read the row while it is not yet revoked. Without the atomic guard
    # both would mint a pair and fork the token family.
    async with maker() as s1, maker() as s2:
        for s in (s1, s2):
            pre = (
                await s.execute(
                    select(OAuthToken.revoked_at).where(
                        OAuthToken.refresh_token_hash == oauth.hash_token(refresh)
                    )
                )
            ).scalar_one()
            assert pre is None

        try:
            await oauth_service.refresh_tokens(s1, **_kw(refresh, client_id, now))  # type: ignore[arg-type]
            await s1.commit()
            winners += 1
        except oauth.OAuthError:
            await s1.rollback()
            losers += 1

        try:
            await oauth_service.refresh_tokens(s2, **_kw(refresh, client_id, now))  # type: ignore[arg-type]
            await s2.commit()
            winners += 1
        except oauth.OAuthError:
            await s2.rollback()
            losers += 1

    assert winners == 1, "exactly one refresh may rotate the token family"
    assert losers == 1, "the second refresh must be rejected as invalid_grant"

    # Only one active row is left, the freshly rotated pair. The family did not fork.
    async with maker() as check:
        live = (
            await check.execute(
                select(OAuthToken).where(
                    OAuthToken.principal_id == principal_id,
                    OAuthToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert len(live) == 1


async def test_reuse_of_rotated_token_revokes_family(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    principal_id, client_id, refresh = await _seed_principal_with_token(maker)

    # A legitimate rotation turns the old token into a new pair.
    async with maker() as s:
        issued = await oauth_service.refresh_tokens(
            s, **_kw(refresh, client_id, datetime.now(UTC))  # type: ignore[arg-type]
        )
        await s.commit()
        new_refresh = issued.refresh_token

    # A replay of the old and now revoked token gives invalid_grant and revokes the family.
    async with maker() as s:
        with pytest.raises(oauth.OAuthError) as exc:
            await oauth_service.refresh_tokens(
                s, **_kw(refresh, client_id, datetime.now(UTC))  # type: ignore[arg-type]
            )
        assert exc.value.error == "invalid_grant"
        await s.commit()

    # The revoke cascades to the fresh token of the family, so no active row is left.
    async with maker() as check:
        live = (
            await check.execute(
                select(OAuthToken).where(
                    OAuthToken.principal_id == principal_id,
                    OAuthToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert live == []

    # A rotation with the previously fresh token therefore fails as well.
    async with maker() as s:
        with pytest.raises(oauth.OAuthError):
            await oauth_service.refresh_tokens(
                s, **_kw(new_refresh, client_id, datetime.now(UTC))  # type: ignore[arg-type]
            )
