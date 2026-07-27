"""OIDC login against Keycloak: authorization code plus PKCE, confidential client.

The module derives the endpoints from the realm `issuer` by the Keycloak convention. It
runs no discovery roundtrip at startup. It exchanges the code over `httpx`. It verifies the
signature of the `id_token` against the JWKS with RS256 and checks `aud`, `iss` and
`nonce`. Every network failure and every verification failure raises `OidcError`. The
service maps that error to a 400 or a 503.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from app.settings import Settings

_VERIFIER_BYTES = 64
_HTTP_TIMEOUT = 10.0


class OidcError(RuntimeError):
    """The OIDC flow failed at the network, the token exchange, the signature or a claim."""


@dataclass(slots=True)
class OidcClaims:
    sub: str
    email: str | None
    name: str | None
    groups: list[str] = field(default_factory=list)
    # `email_verified` is the standard OIDC claim. Only a verified claim may count for the
    # email bootstrap. Otherwise, on an IdP with self-registration and no mail
    # verification, any account could get a token with `email` set to a bootstrap-admin
    # address and become admin on the first login.
    email_verified: bool = False


def generate_pkce() -> tuple[str, str]:
    """Generate the `code_verifier` and the `code_challenge` (S256, unpadded, RFC 7636)."""
    verifier = secrets.token_urlsafe(_VERIFIER_BYTES)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)


def _endpoint(issuer: str, suffix: str) -> str:
    return f"{issuer.rstrip('/')}/protocol/openid-connect/{suffix}"


def authorization_url(settings: Settings, *, state: str, challenge: str, nonce: str) -> str:
    """Build the Keycloak authorize URL for the authorization code flow with PKCE."""
    params = {
        "client_id": settings.oidc_client_id or "",
        "response_type": "code",
        "redirect_uri": settings.oidc_redirect_url or "",
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return _endpoint(settings.oidc_issuer or "", "auth") + "?" + urlencode(params)


async def exchange_code(settings: Settings, *, code: str, verifier: str) -> dict[str, str]:
    """Exchange the authorization code for a token set.

    The request carries the credentials of the confidential client and the PKCE verifier.

    Raises:
        OidcError: The token endpoint is unreachable, the exchange fails, or the response
            carries no `id_token`.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_url or "",
        "client_id": settings.oidc_client_id or "",
        "client_secret": settings.oidc_client_secret or "",
        "code_verifier": verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(_endpoint(settings.oidc_issuer or "", "token"), data=data)
    except httpx.HTTPError as exc:
        raise OidcError(f"token endpoint unreachable: {exc}") from exc
    if resp.status_code != httpx.codes.OK:
        raise OidcError(f"token exchange failed: {resp.status_code}")
    payload = resp.json()
    if "id_token" not in payload:
        raise OidcError("token response without id_token")
    return payload


# JWKS cache per issuer, as a pair of monotonic expiry time and keys. The TTL bounds the
# load on the IdP and the DoS amplification. An unknown `kid` forces one reload for a key
# rotation. A second miss is an error.
_JWKS_TTL_SECONDS = 300.0
_jwks_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _monotonic() -> float:
    return time.monotonic()


async def _fetch_jwks(issuer: str) -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(_endpoint(issuer, "certs"))
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise OidcError(f"jwks unreachable: {exc}") from exc
    keys = resp.json().get("keys", [])
    _jwks_cache[issuer] = (_monotonic() + _JWKS_TTL_SECONDS, keys)
    return keys


async def _get_jwks(issuer: str, *, force: bool) -> list[dict[str, Any]]:
    cached = _jwks_cache.get(issuer)
    if not force and cached is not None and cached[0] > _monotonic():
        return cached[1]
    return await _fetch_jwks(issuer)


def _find_key(keys: list[dict[str, Any]], kid: object) -> dict[str, Any] | None:
    return next((k for k in keys if k.get("kid") == kid), None)


async def _signing_key(settings: Settings, id_token: str) -> Any:
    """Return the TTL-cached JWKS key that matches the `kid` of the `id_token`."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OidcError(f"malformed id_token: {exc}") from exc
    kid = header.get("kid")
    issuer = settings.oidc_issuer or ""
    keys = await _get_jwks(issuer, force=False)
    jwk = _find_key(keys, kid)
    if jwk is None:
        # The cache can be stale after a key rotation, so force one reload.
        keys = await _get_jwks(issuer, force=True)
        jwk = _find_key(keys, kid)
    if jwk is None:
        raise OidcError("no matching jwks key")
    return RSAAlgorithm.from_jwk(json.dumps(jwk))


async def verify_id_token(settings: Settings, *, id_token: str, nonce: str) -> OidcClaims:
    """Verify the signature and the claims of the `id_token`.

    The function checks `aud`, `iss`, `exp` and `nonce`.

    Raises:
        OidcError: The token is malformed or invalid, or the nonce does not match.
    """
    key = await _signing_key(settings, id_token)
    try:
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OidcError(f"id_token invalid: {exc}") from exc
    if claims.get("nonce") != nonce:
        raise OidcError("nonce mismatch")
    groups = claims.get(settings.oidc_groups_claim) or []
    if not isinstance(groups, list):
        groups = []
    return OidcClaims(
        sub=str(claims["sub"]),
        email=claims.get("email"),
        name=claims.get("name") or claims.get("preferred_username"),
        groups=[str(g) for g in groups],
        email_verified=claims.get("email_verified") is True,
    )


def end_session_url(settings: Settings, *, id_token: str | None) -> str | None:
    """Build the Keycloak logout URL.

    The URL carries an optional `id_token_hint` and an optional
    `post_logout_redirect_uri`.

    Returns:
        The logout URL, or `None` when no OIDC issuer is configured.
    """
    if not settings.oidc_issuer:
        return None
    params: dict[str, str] = {}
    if id_token:
        params["id_token_hint"] = id_token
    if settings.oidc_post_logout_redirect_url:
        params["post_logout_redirect_uri"] = settings.oidc_post_logout_redirect_url
    url = _endpoint(settings.oidc_issuer, "logout")
    if params:
        url += "?" + urlencode(params)
    return url
