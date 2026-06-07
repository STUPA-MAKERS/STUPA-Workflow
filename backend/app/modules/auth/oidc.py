"""OIDC / Keycloak: Authorization Code + PKCE, Confidential Client (security.md §2).

Endpunkte werden aus dem Realm-`issuer` nach Keycloak-Konvention abgeleitet (kein
Discovery-Roundtrip beim Start). Token-Exchange via `httpx`; `id_token` wird gegen
das JWKS signaturgeprüft (RS256) inkl. `aud`/`iss`/`nonce`. Alle Netz-/Verify-Fehler
werden als `OidcError` signalisiert — der Service mappt sie auf 400/503.
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
    """OIDC-Flow fehlgeschlagen (Netz, Token-Exchange, Signatur, Claims)."""


@dataclass(slots=True)
class OidcClaims:
    sub: str
    email: str | None
    name: str | None
    groups: list[str] = field(default_factory=list)
    # `email_verified` (OIDC-Standard-Claim). Nur ein **verifizierter** Claim darf für
    # den E-Mail-Bootstrap (#70) zählen — sonst könnte auf einem IdP mit
    # Self-Registration ohne Mail-Verifikation ein beliebiger Account einen Token mit
    # `email` = Bootstrap-Admin-Adresse minten und so beim ersten Login Admin werden.
    email_verified: bool = False


def generate_pkce() -> tuple[str, str]:
    """(`code_verifier`, `code_challenge`) — S256, ohne Padding (RFC 7636)."""
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
    """Keycloak-Authorize-URL (Auth Code + PKCE) bauen."""
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
    """Authorization Code → Token-Set (Confidential Client + PKCE-verifier)."""
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


# JWKS-Cache je issuer: (Ablauf-Monotonzeit, keys). TTL begrenzt IdP-Last +
# DoS-Amplifikation; bei unbekannter `kid` wird einmalig erzwungen neu geladen
# (Key-Rotation), danach Fehler (security.md §2/§11).
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
    """Passenden JWKS-Schlüssel (`kid`) als Key-Objekt für PyJWT — mit TTL-Cache."""
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OidcError(f"malformed id_token: {exc}") from exc
    kid = header.get("kid")
    issuer = settings.oidc_issuer or ""
    keys = await _get_jwks(issuer, force=False)
    jwk = _find_key(keys, kid)
    if jwk is None:
        # Cache evtl. veraltet (Rotation) → einmalig erzwungen neu laden.
        keys = await _get_jwks(issuer, force=True)
        jwk = _find_key(keys, kid)
    if jwk is None:
        raise OidcError("no matching jwks key")
    return RSAAlgorithm.from_jwk(json.dumps(jwk))


async def verify_id_token(settings: Settings, *, id_token: str, nonce: str) -> OidcClaims:
    """`id_token` signatur-/claim-prüfen (aud/iss/exp/nonce) → `OidcClaims`."""
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
    """Keycloak-Logout-URL (optional id_token_hint + post_logout_redirect)."""
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
