"""Altcha-Challenge-Endpunkt (security.md §7, Issue #23).

`GET /api/altcha/challenge` liefert eine frische, HMAC-signierte PoW-Challenge. Das FE
löst sie und sendet die Lösung im `altcha`-Feld der öffentlichen POSTs; der Server
verifiziert sie dort serverseitig (`app.shared.antiabuse.require_altcha`).

Ohne konfiguriertes `ALTCHA_HMAC_SECRET` ist Altcha **aus** → 404 (kein Captcha-Flow).
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
    """Altcha-PoW-Challenge (altcha-lib-Format) für das FE."""

    algorithm: str
    challenge: str
    salt: str
    signature: str
    maxnumber: int


@router.get("/altcha/challenge", response_model=AltchaChallengeOut, responses={404: _PROBLEM})
def altcha_challenge(settings: SettingsDep) -> AltchaChallengeOut:
    """Frische PoW-Challenge ausgeben (404, wenn Altcha nicht konfiguriert)."""
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
