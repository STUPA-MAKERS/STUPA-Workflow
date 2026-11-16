"""Unit: the route `GET /auth/me/profile` (§F/administration/accounts/001120)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import jwt
import pytest

from app.deps import Principal
from app.modules.account import router as account_mod
from app.modules.auth import sessions
from app.settings import load_settings
from tests._support.flow_fakes import fake_session, result

SETTINGS = load_settings(
    database_url="postgresql+asyncpg://x/y",
    session_secret="session-secret-0123456",
    magic_link_secret="magic-link-secret-0",
    public_base_url="https://antrag.example",
    cookie_secure=False,
)
PID = uuid.uuid4()
LOGIN = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
TOKEN = jwt.encode(
    {"sub": "u1", "given_name": "Ada", "nonce": "n"},
    "secret-0123456789-0123456789-0123",
    algorithm="HS256",
)


def _request(cookie: str | None = None) -> Any:
    cookies = {SETTINGS.session_cookie_name: cookie} if cookie else {}
    return SimpleNamespace(cookies=cookies)


def _row() -> SimpleNamespace:
    return SimpleNamespace(id=PID, oidc_groups=["stupa"], last_login=LOGIN)


def _sessions(monkeypatch: pytest.MonkeyPatch, row: object) -> None:
    async def _load(*_a: object, **_kw: object) -> object:
        return row

    monkeypatch.setattr(sessions, "load_principal_session", _load)


async def test_profile_without_a_principal_row_uses_the_principal() -> None:
    principal = Principal(sub="u1", email="a@x.de", display_name="Ada", groups={"b", "a"})
    out = await account_mod.my_profile(_request("c"), principal, fake_session(result()), SETTINGS)
    assert out.last_login is None
    assert {c.key: c.value for c in out.claims} == {
        "sub": "u1",
        "email": "a@x.de",
        "name": "Ada",
        "groups": ["a", "b"],
    }


async def test_profile_reads_the_claims_of_the_own_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sessions(monkeypatch, SimpleNamespace(principal_id=PID, id_token=TOKEN))
    out = await account_mod.my_profile(
        _request("c"), Principal(sub="u1"), fake_session(result(_row())), SETTINGS
    )
    assert out.last_login == LOGIN
    assert {c.key: c.value for c in out.claims} == {"sub": "u1", "given_name": "Ada"}


async def test_profile_of_a_scoped_token_reads_no_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sessions(monkeypatch, SimpleNamespace(principal_id=PID, id_token=TOKEN))
    capped = Principal(sub="u1", scope_permissions=frozenset({"application.read"}))
    out = await account_mod.my_profile(
        _request("c"), capped, fake_session(result(_row())), SETTINGS
    )
    assert {c.key for c in out.claims} == {"sub", "groups"}


async def test_own_session_token_needs_a_cookie() -> None:
    assert (
        await account_mod._own_session_id_token(_request(), fake_session(), SETTINGS, PID) is None
    )


@pytest.mark.parametrize(
    "row",
    [None, SimpleNamespace(principal_id=uuid.uuid4(), id_token=TOKEN)],
    ids=["no-session", "other-principal"],
)
async def test_own_session_token_needs_the_own_session(
    monkeypatch: pytest.MonkeyPatch, row: object
) -> None:
    _sessions(monkeypatch, row)
    assert (
        await account_mod._own_session_id_token(_request("c"), fake_session(), SETTINGS, PID)
        is None
    )
