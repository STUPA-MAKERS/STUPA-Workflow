"""ALTCHA challenge endpoint.

`GET /api/altcha/challenge` issues a fresh HMAC-signed proof-of-work challenge. The
frontend solves the challenge. The public POST routes then verify the solution on the
server with `app.shared.antiabuse.require_altcha`. Without `ALTCHA_HMAC_SECRET` the
feature is off and the endpoint returns 404.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.shared.altcha import create_challenge
from app.shared.antiabuse import SettingsDep, now_unix
from app.shared.errors import NotFoundError, ProblemDetail

router = APIRouter(tags=["antiabuse"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


class AltchaChallengeOut(BaseModel):
    """ALTCHA proof-of-work challenge in the altcha-lib format."""

    algorithm: str
    challenge: str
    salt: str
    signature: str
    maxnumber: int


@router.get("/altcha/challenge", response_model=AltchaChallengeOut, responses={404: _PROBLEM})
def altcha_challenge(settings: SettingsDep) -> AltchaChallengeOut:
    """Issue a fresh proof-of-work challenge.

    The route returns 404 if ALTCHA is not configured.
    """
    if not settings.altcha_enabled:
        raise NotFoundError("Altcha is not configured.")
    assert settings.altcha_hmac_secret is not None
    challenge = create_challenge(
        settings.altcha_hmac_secret,
        expires=now_unix() + settings.altcha_challenge_ttl_seconds,
        max_number=settings.altcha_max_number,
    )
    return AltchaChallengeOut(
        algorithm=challenge.algorithm,
        challenge=challenge.challenge,
        salt=challenge.salt,
        signature=challenge.signature,
        maxnumber=challenge.maxnumber,
    )
