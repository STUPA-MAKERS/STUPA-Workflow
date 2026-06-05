"""TDD: OIDC/Keycloak (security.md §2) — PKCE, Token-Exchange, id_token-Verify."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.modules.auth import oidc
from app.modules.auth.oidc import OidcError
from app.settings import Settings, load_settings

ISSUER = "https://kc.example/realms/app"
CLIENT_ID = "antrag"
CERTS = f"{ISSUER}/protocol/openid-connect/certs"
TOKEN = f"{ISSUER}/protocol/openid-connect/token"


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x/y",
        "session_secret": "s",
        "magic_link_secret": "m",
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": "secret",
        "oidc_redirect_url": "https://antrag.example/api/auth/callback",
    }
    base.update(over)
    return load_settings(**base)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_pkce_pair_and_state_nonce() -> None:
    verifier, challenge = oidc.generate_pkce()
    assert verifier and challenge
    assert "=" not in challenge  # ohne Padding
    assert oidc.generate_state() != oidc.generate_state()
    assert oidc.generate_nonce() != oidc.generate_nonce()


def test_authorization_url_contains_pkce_params() -> None:
    url = oidc.authorization_url(_settings(), state="st", challenge="ch", nonce="nc")
    assert url.startswith(f"{ISSUER}/protocol/openid-connect/auth?")
    for part in ("code_challenge=ch", "code_challenge_method=S256", "state=st",
                 "nonce=nc", f"client_id={CLIENT_ID}", "response_type=code"):
        assert part in url


def test_end_session_url_variants() -> None:
    assert oidc.end_session_url(_settings(oidc_issuer=None), id_token="x") is None
    plain = oidc.end_session_url(_settings(), id_token=None)
    assert plain == f"{ISSUER}/protocol/openid-connect/logout"
    full = oidc.end_session_url(
        _settings(oidc_post_logout_redirect_url="https://antrag.example/bye"),
        id_token="idt",
    )
    assert full is not None
    assert "id_token_hint=idt" in full
    assert "post_logout_redirect_uri=" in full


# --------------------------------------------------------------------------- #
# Token-Exchange
# --------------------------------------------------------------------------- #
async def test_exchange_code_ok() -> None:
    with respx.mock:
        respx.post(TOKEN).mock(
            return_value=httpx.Response(200, json={"id_token": "idt", "refresh_token": "rt"})
        )
        out = await oidc.exchange_code(_settings(), code="c", verifier="v")
    assert out["id_token"] == "idt"


async def test_exchange_code_missing_id_token() -> None:
    with respx.mock:
        respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "a"}))
        with pytest.raises(OidcError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


async def test_exchange_code_non_200() -> None:
    with respx.mock:
        respx.post(TOKEN).mock(return_value=httpx.Response(400, json={"error": "bad"}))
        with pytest.raises(OidcError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


async def test_exchange_code_unreachable() -> None:
    with respx.mock:
        respx.post(TOKEN).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(OidcError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


# --------------------------------------------------------------------------- #
# id_token-Verify (echtes RS256)
# --------------------------------------------------------------------------- #
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "k1"


def _jwk() -> dict[str, object]:
    pub = json.loads(RSAAlgorithm.to_jwk(_KEY.public_key()))
    pub["kid"] = _KID
    return pub


def _id_token(**claims: object) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "sub": "user-1",
        "aud": CLIENT_ID,
        "iss": ISSUER,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    payload.update(claims)
    return jwt.encode(payload, _KEY, algorithm="RS256", headers={"kid": _KID})  # type: ignore[arg-type]


async def test_verify_id_token_happy() -> None:
    token = _id_token(email="e@x.de", name="N", nonce="nc", groups=["stupa", "asta"])
    with respx.mock:
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        claims = await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
    assert claims.sub == "user-1"
    assert claims.email == "e@x.de"
    assert claims.groups == ["stupa", "asta"]


async def test_verify_id_token_groups_non_list_falls_back() -> None:
    token = _id_token(nonce="nc", groups="not-a-list", preferred_username="pu")
    with respx.mock:
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        claims = await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
    assert claims.groups == []
    assert claims.name == "pu"  # Fallback auf preferred_username


async def test_verify_id_token_nonce_mismatch() -> None:
    token = _id_token(nonce="other")
    with respx.mock:
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_malformed() -> None:
    with pytest.raises(OidcError):
        await oidc.verify_id_token(_settings(), id_token="not-a-jwt", nonce="nc")


async def test_verify_id_token_jwks_unreachable() -> None:
    token = _id_token(nonce="nc")
    with respx.mock:
        respx.get(CERTS).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_no_matching_kid() -> None:
    token = _id_token(nonce="nc")
    other = _jwk()
    other["kid"] = "different"
    with respx.mock:
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [other]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_wrong_audience() -> None:
    token = _id_token(aud="someone-else", nonce="nc")
    with respx.mock:
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
