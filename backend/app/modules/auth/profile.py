"""The claims of the profile page (`GET /auth/me/profile`).

The page shows what the platform has from the SSO about the signed-in person. The source
is the `id_token` of the current session (`auth_session.id_token`). The callback and the
refresh verified its signature before they stored it, so this module reads the payload
without a second check and keeps no new data.

The page shows only the claims about the person. The claims of the token itself
(`TECHNICAL_CLAIMS`) stay hidden, because they tell the person nothing about the profile
(§F/administration/accounts/001121).
"""

from __future__ import annotations

from typing import Any

import jwt

#: The claims of the token mechanics: issuer, audience, times, nonce, hashes, session.
TECHNICAL_CLAIMS: frozenset[str] = frozenset(
    {
        "iss",
        "aud",
        "exp",
        "iat",
        "nbf",
        "auth_time",
        "nonce",
        "at_hash",
        "c_hash",
        "s_hash",
        "azp",
        "sid",
        "jti",
        "acr",
        "amr",
    }
)


def id_token_claims(id_token: str | None) -> dict[str, Any]:
    """Return the payload of a stored `id_token`, or an empty dict.

    A token that does not decode gives an empty dict, so the page falls back to the
    stored fields instead of an error.
    """
    if not id_token:
        return {}
    try:
        payload = jwt.decode(id_token, options={"verify_signature": False})
    except jwt.PyJWTError:
        return {}
    return payload if isinstance(payload, dict) else {}


def person_claims(
    claims: dict[str, Any],
    *,
    sub: str,
    email: str | None,
    name: str | None,
    groups: list[str] | None,
) -> list[tuple[str, Any]]:
    """Return the claims about the person, sorted by key, without `TECHNICAL_CLAIMS`.

    Without a token (an OAuth bearer request, or a session from before the token was kept)
    the stored fields of the principal stand in for the claims.
    """
    if not claims:
        claims = {"sub": sub, "email": email, "name": name, "groups": groups or []}
    return sorted(
        ((k, v) for k, v in claims.items() if k not in TECHNICAL_CLAIMS and v is not None),
        key=lambda kv: kv[0],
    )
