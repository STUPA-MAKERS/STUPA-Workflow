"""Session renewal: the periodic check of a long principal session at the IdP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.auth import oidc, service, session_renewal
from app.modules.auth.models import (
    DEFAULT_PWA_SESSION_DAYS,
    DEFAULT_WEB_SESSION_DAYS,
    AuthSession,
    LoginSettings,
)
from app.modules.auth.oidc import OidcClaims, OidcError, OidcUnavailableError
from app.modules.auth.session_renewal import renew_principal_session, session_expiry
from app.settings import Settings, load_settings
from app.shared.errors import ForbiddenError
from tests._support.auth_fakes import fake_session, result

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x/y",
        "session_secret": "session-secret-0123",
        "magic_link_secret": "magic-link-secret-0",
        "oidc_issuer": "https://sso.example/",
        "oidc_client_id": "antrag",
        "oidc_client_secret": "client-secret-01234",
        "oidc_redirect_url": "https://antrag.example/api/auth/callback",
    }
    base.update(over)
    return load_settings(**base)


def _row(
    *,
    checked_hours_ago: float | None = 13,
    refresh_token: str | None = "rt1",
    client: str = "web",
) -> AuthSession:
    row = AuthSession(
        sid="s",
        principal_id="pid",
        expires_at=NOW + timedelta(days=1),
        refresh_token=refresh_token,
        id_token="old-idt",
        client=client,
    )
    if checked_hours_ago is not None:
        row.revalidated_at = NOW - timedelta(hours=checked_hours_ago)
    return row


def _principal(*, active: bool = True) -> Any:
    return SimpleNamespace(
        sub="user-1", active=active, email="e@x.de", display_name="N", oidc_groups=["old"]
    )


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the IdP calls and the principal update. The dict drives the outcome."""
    state: dict[str, Any] = {
        "refresh": {"id_token": "new-idt", "refresh_token": "rt2"},
        "verify": OidcClaims(sub="user-1", email=None, name=None, groups=["stupa"]),
        "upsert": SimpleNamespace(sub="user-1", active=True),
        "synced": [],
    }

    async def _refresh(_s: Settings, *, refresh_token: str) -> dict[str, str]:
        state["used_token"] = refresh_token
        out = state["refresh"]
        if isinstance(out, Exception):
            raise out
        return out

    async def _verify(_s: Settings, *, id_token: str, cached: OidcClaims) -> OidcClaims:
        state["cached"] = cached
        out = state["verify"]
        if isinstance(out, Exception):
            raise out
        return out

    async def _upsert(_db: object, _claims: OidcClaims) -> Any:
        out = state["upsert"]
        if isinstance(out, Exception):
            raise out
        return out

    async def _sync(_db: object, row: object) -> None:
        state["synced"].append(row)

    monkeypatch.setattr(oidc, "refresh_tokens", _refresh)
    monkeypatch.setattr(oidc, "verify_refreshed_id_token", _verify)
    monkeypatch.setattr(service, "upsert_principal", _upsert)
    monkeypatch.setattr(session_renewal, "sync_principal_memberships", _sync)
    monkeypatch.setattr(session_renewal, "_idp_retry_after", 0.0)
    return state


async def test_not_due_touches_nothing(idp: dict[str, Any]) -> None:
    row = _row(checked_hours_ago=1)
    db = fake_session()
    assert await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert db.committed == 0
    assert "used_token" not in idp


async def test_renews_and_slides(idp: dict[str, Any]) -> None:
    row = _row()
    db = fake_session(result(row))
    assert await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert idp["used_token"] == "rt1"
    assert row.refresh_token == "rt2"
    assert row.id_token == "new-idt"
    assert row.revalidated_at == NOW
    assert row.expires_at == NOW + timedelta(days=DEFAULT_WEB_SESSION_DAYS)
    assert idp["synced"] == [idp["upsert"]]
    assert db.committed == 2  # tokens first, then the check
    assert db.deleted == []


async def test_pwa_session_gets_the_app_lifetime(idp: dict[str, Any]) -> None:
    row = _row(client="pwa")
    db = fake_session(result(row))
    assert await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert row.expires_at == NOW + timedelta(days=DEFAULT_PWA_SESSION_DAYS)


async def test_keeps_old_refresh_token_when_idp_does_not_rotate(idp: dict[str, Any]) -> None:
    idp["refresh"] = {"id_token": "new-idt"}
    row = _row()
    db = fake_session(result(row))
    assert await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert row.refresh_token == "rt1"


async def test_row_without_check_time_is_due(idp: dict[str, Any]) -> None:
    row = _row(checked_hours_ago=None)
    db = fake_session(result(row))
    assert await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert idp["used_token"] == "rt1"


async def test_locked_by_other_request_goes_on(idp: dict[str, Any]) -> None:
    db = fake_session(result(), result("session-id"))
    assert await renew_principal_session(
        db, _settings(), session=_row(), principal=_principal(), now=NOW
    )
    assert "used_token" not in idp
    assert db.committed == 0


async def test_renewed_by_other_request_meanwhile(idp: dict[str, Any]) -> None:
    fresh = _row(checked_hours_ago=0)
    db = fake_session(result(fresh))
    assert await renew_principal_session(
        db, _settings(), session=_row(), principal=_principal(), now=NOW
    )
    assert "used_token" not in idp
    assert db.committed == 1


async def test_no_refresh_token_ends_session(idp: dict[str, Any]) -> None:
    row = _row(refresh_token=None)
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert db.deleted == [row]
    assert db.committed == 1


async def test_oidc_off_ends_session(idp: dict[str, Any]) -> None:
    row = _row()
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(oidc_issuer=None), session=row, principal=_principal(), now=NOW
    )
    assert db.deleted == [row]


@pytest.mark.parametrize(
    "key,value",
    [
        ("refresh", OidcError("invalid_grant")),
        ("verify", OidcError("sub mismatch")),
        ("upsert", ForbiddenError("merged", code="account_merged")),
        ("upsert", SimpleNamespace(sub="user-1", active=False)),
    ],
)
async def test_refusal_ends_session(idp: dict[str, Any], key: str, value: object) -> None:
    idp[key] = value
    row = _row()
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert db.deleted == [row]
    assert idp["synced"] == []


async def test_outage_keeps_session_within_grace(idp: dict[str, Any]) -> None:
    idp["refresh"] = OidcUnavailableError("down")
    row = _row(checked_hours_ago=20)
    db = fake_session(result(row))
    assert await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert db.deleted == []
    assert db.committed == 1
    assert row.revalidated_at == NOW - timedelta(hours=20)


async def test_outage_past_grace_ends_session(idp: dict[str, Any]) -> None:
    idp["refresh"] = OidcUnavailableError("down")
    row = _row(checked_hours_ago=80)
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert db.deleted == [row]


async def test_outage_on_row_without_check_time_ends_session(idp: dict[str, Any]) -> None:
    idp["refresh"] = OidcUnavailableError("down")
    row = _row(checked_hours_ago=None)
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )


async def test_session_expiry_reads_the_settings_row() -> None:
    stored = LoginSettings(id=1, web_session_days=30, pwa_session_days=60)
    db = fake_session(gets=[stored, stored])
    assert await session_expiry(db, "web", NOW) == NOW + timedelta(days=30)
    assert await session_expiry(db, "pwa", NOW) == NOW + timedelta(days=60)


async def test_cached_claims_come_from_the_principal(idp: dict[str, Any]) -> None:
    row = _row()
    await renew_principal_session(
        fake_session(result(row)), _settings(), session=row, principal=_principal(), now=NOW
    )
    assert idp["cached"] == OidcClaims(
        sub="user-1", email="e@x.de", name="N", groups=["old"]
    )


async def test_new_tokens_are_committed_before_the_principal_update(
    idp: dict[str, Any],
) -> None:
    idp["upsert"] = ForbiddenError("merged", code="account_merged")
    row = _row()
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    # One commit for the tokens, one for the end of the session.
    assert db.committed == 2
    assert row.refresh_token == "rt2"


async def test_session_past_the_absolute_lifetime_ends(idp: dict[str, Any]) -> None:
    row = _row()
    row.created_at = NOW - timedelta(days=401)
    db = fake_session(result(row))
    assert not await renew_principal_session(
        db, _settings(), session=row, principal=_principal(), now=NOW
    )
    assert db.deleted == [row]
    assert "used_token" not in idp


async def test_deleted_row_does_not_go_on(idp: dict[str, Any]) -> None:
    db = fake_session(result(), result())
    assert not await renew_principal_session(
        db, _settings(), session=_row(), principal=_principal(), now=NOW
    )


async def test_outage_backs_off_without_calling_the_idp(
    idp: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    idp["refresh"] = OidcUnavailableError("down")
    row = _row(checked_hours_ago=20)
    assert await renew_principal_session(
        fake_session(result(row)), _settings(), session=row, principal=_principal(), now=NOW
    )
    del idp["used_token"]
    other = _row(checked_hours_ago=20)
    db = fake_session()
    assert await renew_principal_session(
        db, _settings(), session=other, principal=_principal(), now=NOW
    )
    assert "used_token" not in idp
    assert db.committed == 0
    # Past the grace time the backoff does not protect the session.
    old = _row(checked_hours_ago=80)
    db = fake_session(result(old))
    assert not await renew_principal_session(
        db, _settings(), session=old, principal=_principal(), now=NOW
    )
