"""TDD: OIDC (security.md §2) — discovery, PKCE, token exchange, id_token verify.

The IdP here is shaped like authentik: the issuer ends in a slash, and the endpoints do
not sit under the issuer path. A module that builds a URL from the issuer instead of
reading the discovery document fails these tests.
"""

from __future__ import annotations

import base64
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

ISSUER = "https://sso.example/application/o/antrag/"
CLIENT_ID = "antrag"
DISCOVERY = "https://sso.example/application/o/antrag/.well-known/openid-configuration"
AUTHORIZE = "https://sso.example/application/o/authorize/"
TOKEN = "https://sso.example/application/o/token/"
CERTS = "https://sso.example/application/o/antrag/jwks/"
END_SESSION = "https://sso.example/application/o/antrag/end-session/"


def _doc(**over: object) -> dict[str, object]:
    doc: dict[str, object] = {
        "issuer": ISSUER,
        "authorization_endpoint": AUTHORIZE,
        "token_endpoint": TOKEN,
        "jwks_uri": CERTS,
        "end_session_endpoint": END_SESSION,
    }
    doc.update(over)
    return {k: v for k, v in doc.items() if v is not None}


def _serve_discovery(**over: object) -> respx.Route:
    """Serve the discovery document inside an active `respx.mock`."""
    return respx.get(DISCOVERY).mock(return_value=httpx.Response(200, json=_doc(**over)))


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x/y",
        "session_secret": "session-secret-0123",
        "magic_link_secret": "magic-link-secret-0",
        "oidc_issuer": ISSUER,
        "oidc_client_id": CLIENT_ID,
        "oidc_client_secret": "client-secret-01234",
        "oidc_redirect_url": "https://antrag.example/api/auth/callback",
    }
    base.update(over)
    return load_settings(**base)


@pytest.fixture(autouse=True)
def _clear_caches() -> object:
    oidc._jwks_cache.clear()
    oidc._discovery_cache.clear()
    yield
    oidc._jwks_cache.clear()
    oidc._discovery_cache.clear()


def test_pkce_pair_and_state_nonce() -> None:
    verifier, challenge = oidc.generate_pkce()
    assert verifier and challenge
    assert "=" not in challenge  # no padding
    assert oidc.generate_state() != oidc.generate_state()
    assert oidc.generate_nonce() != oidc.generate_nonce()


async def test_authorization_url_contains_pkce_params() -> None:
    with respx.mock:
        _serve_discovery()
        url = await oidc.authorization_url(
            _settings(), state="st", challenge="ch", nonce="nc"
        )
    assert url.startswith(f"{AUTHORIZE}?")
    for part in ("code_challenge=ch", "code_challenge_method=S256", "state=st",
                 "nonce=nc", f"client_id={CLIENT_ID}", "response_type=code"):
        assert part in url


async def test_end_session_url_variants() -> None:
    assert await oidc.end_session_url(_settings(oidc_issuer=None), id_token="x") is None
    with respx.mock:
        _serve_discovery()
        plain = await oidc.end_session_url(_settings(), id_token=None)
        full = await oidc.end_session_url(
            _settings(oidc_post_logout_redirect_url="https://antrag.example/bye"),
            id_token="idt",
        )
    assert plain == END_SESSION
    assert full is not None
    assert "id_token_hint=idt" in full
    assert "post_logout_redirect_uri=" in full


async def test_exchange_code_ok() -> None:
    with respx.mock:
        _serve_discovery()
        respx.post(TOKEN).mock(
            return_value=httpx.Response(200, json={"id_token": "idt", "refresh_token": "rt"})
        )
        out = await oidc.exchange_code(_settings(), code="c", verifier="v")
    assert out["id_token"] == "idt"


async def test_exchange_code_missing_id_token() -> None:
    with respx.mock:
        _serve_discovery()
        respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "a"}))
        with pytest.raises(OidcError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


async def test_exchange_code_non_200() -> None:
    with respx.mock:
        _serve_discovery()
        respx.post(TOKEN).mock(return_value=httpx.Response(400, json={"error": "bad"}))
        with pytest.raises(OidcError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


async def test_exchange_code_unreachable() -> None:
    with respx.mock:
        _serve_discovery()
        respx.post(TOKEN).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(OidcError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


# The id_token verify tests sign with a real RS256 key.
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
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        claims = await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
    assert claims.sub == "user-1"
    assert claims.email == "e@x.de"
    assert claims.groups == ["stupa", "asta"]
    assert claims.email_verified is False  # the claim is missing, so treat it as unverified


async def test_verify_id_token_email_verified_claim() -> None:
    """`email_verified` counts only when it is strictly True (#70 email bootstrap)."""
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        verified = await oidc.verify_id_token(
            _settings(), id_token=_id_token(nonce="nc", email_verified=True), nonce="nc"
        )
        # A truthy value that is not True, such as the string "true", does not count.
        unverified = await oidc.verify_id_token(
            _settings(), id_token=_id_token(nonce="nc", email_verified="true"), nonce="nc"
        )
    assert verified.email_verified is True
    assert unverified.email_verified is False


async def test_verify_id_token_groups_non_list_falls_back() -> None:
    token = _id_token(nonce="nc", groups="not-a-list", preferred_username="pu")
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        claims = await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
    assert claims.groups == []
    assert claims.name == "pu"  # falls back to preferred_username


async def test_verify_id_token_nonce_mismatch() -> None:
    token = _id_token(nonce="other")
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_malformed() -> None:
    with pytest.raises(OidcError):
        await oidc.verify_id_token(_settings(), id_token="not-a-jwt", nonce="nc")


async def test_verify_id_token_jwks_unreachable() -> None:
    token = _id_token(nonce="nc")
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_no_matching_kid() -> None:
    token = _id_token(nonce="nc")
    other = _jwk()
    other["kid"] = "different"
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [other]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_wrong_audience() -> None:
    token = _id_token(aud="someone-else", nonce="nc")
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_jwks_cached_across_calls() -> None:
    token = _id_token(nonce="nc")
    with respx.mock:
        _serve_discovery()
        route = respx.get(CERTS).mock(
            return_value=httpx.Response(200, json={"keys": [_jwk()]})
        )
        await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
        await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
        assert route.call_count == 1  # the second verify uses the cache


async def test_jwks_refetched_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(oidc, "_monotonic", lambda: clock["t"])
    token = _id_token(nonce="nc")
    with respx.mock:
        _serve_discovery()
        route = respx.get(CERTS).mock(
            return_value=httpx.Response(200, json={"keys": [_jwk()]})
        )
        await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
        clock["t"] = 1000.0 + oidc._JWKS_TTL_SECONDS + 1
        await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
        assert route.call_count == 2  # the TTL expired, so the JWKS loads again


async def test_jwks_force_refetch_on_unknown_kid() -> None:
    token = _id_token(nonce="nc")  # the kid is k1
    stale = _jwk()
    stale["kid"] = "rotated-away"
    with respx.mock:
        _serve_discovery()
        route = respx.get(CERTS).mock(
            side_effect=[
                httpx.Response(200, json={"keys": [stale]}),  # cache without k1
                httpx.Response(200, json={"keys": [_jwk()]}),  # forced reload with k1
            ]
        )
        claims = await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
        assert claims.sub == "user-1"
        assert route.call_count == 2


async def test_verify_id_token_rejects_hs256() -> None:
    # HS256 signature, the algorithm-confusion attack that uses the public key as the HMAC
    # secret. The token carries no kid, so no JWKS key matches and the verify fails.
    now = datetime.now(UTC)
    payload = {
        "sub": "u", "aud": CLIENT_ID, "iss": ISSUER,
        "iat": now, "exp": now + timedelta(hours=1), "nonce": "nc",
    }
    token = jwt.encode(payload, "shared-secret", algorithm="HS256")
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


async def test_verify_id_token_rejects_alg_none() -> None:
    # An unsigned token with alg=none and a matching kid reaches decode. Decode accepts
    # RS256 only, so it raises InvalidAlgorithm, which the module turns into OidcError.
    def _b64(obj: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    now = int(datetime.now(UTC).timestamp())
    header: dict[str, object] = {"alg": "none", "typ": "JWT", "kid": _KID}
    payload: dict[str, object] = {
        "sub": "u", "aud": CLIENT_ID, "iss": ISSUER,
        "iat": now, "exp": now + 3600, "nonce": "nc",
    }
    token = f"{_b64(header)}.{_b64(payload)}."
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        with pytest.raises(OidcError):
            await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")


# Discovery (OpenID Connect Discovery 1.0).


async def test_discovery_serves_all_four_endpoints() -> None:
    """Every endpoint the flow calls comes from the discovery document, none from a path."""
    token = _id_token(nonce="nc")
    with respx.mock:
        discovery = _serve_discovery()
        token_route = respx.post(TOKEN).mock(
            return_value=httpx.Response(200, json={"id_token": token})
        )
        certs_route = respx.get(CERTS).mock(
            return_value=httpx.Response(200, json={"keys": [_jwk()]})
        )
        authorize = await oidc.authorization_url(
            _settings(), state="st", challenge="ch", nonce="nc"
        )
        await oidc.exchange_code(_settings(), code="c", verifier="v")
        await oidc.verify_id_token(_settings(), id_token=token, nonce="nc")
        logout = await oidc.end_session_url(_settings(), id_token=None)
        assert discovery.call_count == 1  # one load serves all four, from the cache
    assert authorize.startswith(f"{AUTHORIZE}?")
    assert token_route.call_count == 1
    assert certs_route.call_count == 1
    assert logout == END_SESSION


async def test_discovery_url_has_no_double_slash() -> None:
    """The issuer ends in a slash. The well-known path must not follow a second one."""
    with respx.mock:
        route = _serve_discovery()
        await oidc.discover(ISSUER)
    assert route.calls.last.request.url == DISCOVERY


async def test_discovery_issuer_mismatch() -> None:
    with respx.mock:
        _serve_discovery(issuer="https://evil.example/application/o/antrag/")
        with pytest.raises(oidc.OidcUnavailableError, match="issuer mismatch"):
            await oidc.discover(ISSUER)
    assert oidc._discovery_cache == {}  # a rejected document is not cached


async def test_discovery_issuer_compare_is_exact() -> None:
    """A missing trailing slash is another issuer, as it is for the `iss` claim."""
    with respx.mock:
        _serve_discovery(issuer=ISSUER.rstrip("/"))
        with pytest.raises(OidcError):
            await oidc.discover(ISSUER)


async def test_discovery_without_end_session_endpoint() -> None:
    with respx.mock:
        _serve_discovery(end_session_endpoint=None)
        url = await oidc.end_session_url(_settings(), id_token="idt")
    assert url is None


async def test_discovery_empty_end_session_endpoint() -> None:
    with respx.mock:
        _serve_discovery(end_session_endpoint="")
        endpoints = await oidc.discover(ISSUER)
    assert endpoints.end_session is None


@pytest.mark.parametrize("field", ["authorization_endpoint", "token_endpoint", "jwks_uri"])
async def test_discovery_missing_required_endpoint(field: str) -> None:
    with respx.mock:
        _serve_discovery(**{field: None})
        with pytest.raises(oidc.OidcUnavailableError, match=field):
            await oidc.discover(ISSUER)


async def test_discovery_non_string_endpoint() -> None:
    with respx.mock:
        _serve_discovery(token_endpoint=42)
        with pytest.raises(oidc.OidcUnavailableError, match="token_endpoint"):
            await oidc.discover(ISSUER)


async def test_discovery_unreachable() -> None:
    with respx.mock:
        respx.get(DISCOVERY).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(oidc.OidcUnavailableError, match="unreachable"):
            await oidc.authorization_url(_settings(), state="s", challenge="c", nonce="n")


async def test_discovery_http_error() -> None:
    with respx.mock:
        respx.get(DISCOVERY).mock(return_value=httpx.Response(404))
        with pytest.raises(oidc.OidcUnavailableError):
            await oidc.discover(ISSUER)


async def test_discovery_not_json() -> None:
    with respx.mock:
        respx.get(DISCOVERY).mock(return_value=httpx.Response(200, text="<html>"))
        with pytest.raises(oidc.OidcUnavailableError, match="not JSON"):
            await oidc.discover(ISSUER)


async def test_discovery_not_an_object() -> None:
    with respx.mock:
        respx.get(DISCOVERY).mock(return_value=httpx.Response(200, json=[ISSUER]))
        with pytest.raises(oidc.OidcUnavailableError, match="not a JSON object"):
            await oidc.discover(ISSUER)


async def test_discovery_cached_across_calls() -> None:
    with respx.mock:
        route = _serve_discovery()
        first = await oidc.discover(ISSUER)
        second = await oidc.discover(ISSUER)
        assert route.call_count == 1
    assert first == second


async def test_discovery_refetched_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"t": 1000.0}
    monkeypatch.setattr(oidc, "_monotonic", lambda: clock["t"])
    with respx.mock:
        route = _serve_discovery()
        await oidc.discover(ISSUER)
        clock["t"] = 1000.0 + oidc._DISCOVERY_TTL_SECONDS + 1
        await oidc.discover(ISSUER)
        assert route.call_count == 2


async def test_exchange_code_unreachable_is_unavailable() -> None:
    """An unreachable token endpoint is an IdP outage, not a rejected login."""
    with respx.mock:
        _serve_discovery()
        respx.post(TOKEN).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(oidc.OidcUnavailableError):
            await oidc.exchange_code(_settings(), code="c", verifier="v")


async def test_exchange_code_rejected_is_not_unavailable() -> None:
    with respx.mock:
        _serve_discovery()
        respx.post(TOKEN).mock(return_value=httpx.Response(400, json={"error": "bad"}))
        with pytest.raises(OidcError) as info:
            await oidc.exchange_code(_settings(), code="c", verifier="v")
    assert not isinstance(info.value, oidc.OidcUnavailableError)


async def test_verify_id_token_iss_matches_configured_issuer_verbatim() -> None:
    """The `iss` claim must equal the configured issuer, trailing slash included."""
    with respx.mock:
        _serve_discovery()
        respx.get(CERTS).mock(return_value=httpx.Response(200, json={"keys": [_jwk()]}))
        ok = await oidc.verify_id_token(
            _settings(), id_token=_id_token(nonce="nc"), nonce="nc"
        )
        with pytest.raises(OidcError):
            await oidc.verify_id_token(
                _settings(), id_token=_id_token(nonce="nc", iss=ISSUER.rstrip("/")), nonce="nc"
            )
    assert ok.sub == "user-1"
