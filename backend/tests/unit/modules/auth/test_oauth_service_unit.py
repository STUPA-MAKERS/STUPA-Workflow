"""Unit: OAuth-Service-Fehlerzweige (``exchange_code``/``refresh_tokens``) ohne DB.

Der Happy-Path liegt in der Integration (``test_oauth_flow``); hier nur die
``invalid_grant``-Zweige (abgelaufener Code, Client-Mismatch, abgelaufener Refresh).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.auth import oauth, oauth_service
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)


async def test_exchange_code_expired_rejected() -> None:
    row = SimpleNamespace(used_at=None, expires_at=NOW - timedelta(seconds=1))
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db,  # pyright: ignore[reportArgumentType]
            code="c",
            code_verifier="v",
            redirect_uri="r",
            client_id="mcp",
            now=NOW,
            access_ttl=3600,
            refresh_ttl=86400,
        )
    assert exc.value.error == "invalid_grant"
    assert "expired" in exc.value.description


async def test_exchange_code_atomic_claim_lost_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Code passiert die Validierung, aber das atomare ``UPDATE ... RETURNING`` liefert
    0 Zeilen (nebenläufig bereits verbraucht, AUD-003) → ``invalid_grant``."""
    monkeypatch.setattr(oauth, "verify_pkce_s256", lambda *_: True)
    row = SimpleNamespace(
        id=uuid4(),
        used_at=None,
        expires_at=NOW + timedelta(minutes=5),
        client_id="mcp",
        redirect_uri="r",
        code_challenge="chal",
    )
    # 1) SELECT liefert die gültige Code-Zeile, 2) UPDATE...RETURNING liefert nichts.
    db = fake_session(result(row), result())
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.exchange_code(
            db,  # pyright: ignore[reportArgumentType]
            code="c",
            code_verifier="v",
            redirect_uri="r",
            client_id="mcp",
            now=NOW,
            access_ttl=3600,
            refresh_ttl=86400,
        )
    assert exc.value.error == "invalid_grant"
    assert "already used" in exc.value.description


async def test_refresh_tokens_atomic_rotate_lost_rejected() -> None:
    """Refresh passiert die Validierung, aber das atomare Rotations-``UPDATE`` liefert
    0 Zeilen (nebenläufig bereits rotiert, AUD-020) → ``invalid_grant``."""
    row = SimpleNamespace(
        id=uuid4(),
        revoked_at=None,
        client_id="mcp",
        refresh_expires_at=None,
        principal_id=uuid4(),
    )
    principal = SimpleNamespace(active=True)
    # 1) SELECT Token, 2) SELECT Principal (aktiv), 3) UPDATE...RETURNING → nichts.
    db = fake_session(result(row), result(principal), result())
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.refresh_tokens(
            db,  # pyright: ignore[reportArgumentType]
            refresh_token="rt",
            client_id="mcp",
            now=NOW,
            access_ttl=3600,
            refresh_ttl=86400,
        )
    assert exc.value.error == "invalid_grant"
    assert "revoked" in exc.value.description


async def test_refresh_tokens_client_mismatch_rejected() -> None:
    row = SimpleNamespace(revoked_at=None, client_id="other", refresh_expires_at=None)
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.refresh_tokens(
            db,  # pyright: ignore[reportArgumentType]
            refresh_token="rt",
            client_id="mcp",
            now=NOW,
            access_ttl=3600,
            refresh_ttl=86400,
        )
    assert "client mismatch" in exc.value.description


async def test_refresh_tokens_expired_rejected() -> None:
    row = SimpleNamespace(
        revoked_at=None, client_id="mcp", refresh_expires_at=NOW - timedelta(seconds=1)
    )
    db = fake_session(result(row))
    with pytest.raises(oauth.OAuthError) as exc:
        await oauth_service.refresh_tokens(
            db,  # pyright: ignore[reportArgumentType]
            refresh_token="rt",
            client_id="mcp",
            now=NOW,
            access_ttl=3600,
            refresh_ttl=86400,
        )
    assert "expired" in exc.value.description
