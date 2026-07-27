"""Unit tests of the OAuth service error branches without a database.

The tests cover `exchange_code` and `refresh_tokens`. The success path lives in the
integration test `test_oauth_flow`. This module covers only the `invalid_grant`
branches: an expired code, a client mismatch and an expired refresh token.
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
    """Reject a code that passes validation but loses the atomic claim.

    The atomic `UPDATE ... RETURNING` returns zero rows, because a concurrent request
    already used the code (AUD-003). The service raises `invalid_grant`.
    """
    monkeypatch.setattr(oauth, "verify_pkce_s256", lambda *_: True)
    row = SimpleNamespace(
        id=uuid4(),
        used_at=None,
        expires_at=NOW + timedelta(minutes=5),
        client_id="mcp",
        redirect_uri="r",
        code_challenge="chal",
    )
    # 1) SELECT returns the valid code row, 2) UPDATE ... RETURNING returns nothing.
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
    """Reject a refresh token that passes validation but loses the atomic rotation.

    The rotation `UPDATE` returns zero rows, because a concurrent request already
    rotated the token (AUD-020). The service raises `invalid_grant`.
    """
    row = SimpleNamespace(
        id=uuid4(),
        revoked_at=None,
        client_id="mcp",
        refresh_expires_at=None,
        principal_id=uuid4(),
    )
    principal = SimpleNamespace(active=True)
    # 1) SELECT token, 2) SELECT principal (active), 3) UPDATE ... RETURNING gives nothing.
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
