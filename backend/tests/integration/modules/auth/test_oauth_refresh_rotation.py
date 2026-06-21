"""Integration: Refresh-Token-Rotation ist atomar + erkennt Wiederverwendung.

Regression für AUD-020:

1. NEBENLÄUFIGE Rotation: zwei Requests mit demselben Refresh-Token dürfen nicht
   beide ein neues Paar erhalten. ``refresh_tokens`` rotiert atomar via
   ``UPDATE ... WHERE id=? AND revoked_at IS NULL RETURNING id`` — der Verlierer
   bekommt ``invalid_grant``, die Token-Familie spaltet sich NICHT auf.

2. REUSE-DETECTION (RFC 6819 §5.2.2.3): wird ein bereits rotiertes (widerrufenes)
   Refresh-Token erneut vorgelegt, wird die gesamte noch aktive Token-Familie des
   Principals + Clients kaskadierend widerrufen, um Neu-Authentisierung zu erzwingen.
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
    """Lege einen aktiven Principal + eine frische Token-Familie an.

    Der ``client_id`` ist pro Test eindeutig, damit die client-gescopten Prüfungen
    anderer Test-Dateien nicht durch diese Zeilen verfälscht werden.
    Gibt ``(principal_id, client_id, refresh_token)`` zurück.
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
    # Zwei getrennte Sessions lesen beide die noch unwiderrufene Zeile, committen dann
    # nacheinander. Ohne den atomaren Guard würden beide ein Paar minten (Familien-Fork).
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

    # Genau EINE noch aktive Zeile (das frisch rotierte Paar) — kein Familien-Fork.
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

    # Legitime Rotation: altes Token → neues Paar.
    async with maker() as s:
        issued = await oauth_service.refresh_tokens(
            s, **_kw(refresh, client_id, datetime.now(UTC))  # type: ignore[arg-type]
        )
        await s.commit()
        new_refresh = issued.refresh_token

    # Replay des ALTEN (jetzt widerrufenen) Tokens → invalid_grant + Familien-Revoke.
    async with maker() as s:
        with pytest.raises(oauth.OAuthError) as exc:
            await oauth_service.refresh_tokens(
                s, **_kw(refresh, client_id, datetime.now(UTC))  # type: ignore[arg-type]
            )
        assert exc.value.error == "invalid_grant"
        await s.commit()

    # Das frische Token der Familie wurde kaskadierend mitwiderrufen → keine aktive Zeile mehr.
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

    # Folgerichtig schlägt auch eine Rotation mit dem zuvor frischen Token fehl.
    async with maker() as s:
        with pytest.raises(oauth.OAuthError):
            await oauth_service.refresh_tokens(
                s, **_kw(new_refresh, client_id, datetime.now(UTC))  # type: ignore[arg-type]
            )
