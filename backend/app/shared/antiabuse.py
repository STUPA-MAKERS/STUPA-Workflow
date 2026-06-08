"""Anti-Abuse-Wiring für öffentliche Endpunkte (Issues #23/#24).

FastAPI-Dependencies, die Body-Cap (413), Rate-Limit (429 + `Retry-After`) und
Altcha-Verifikation (400) **vor** der Endpoint-Logik erzwingen. Backends (Rate-Limiter,
Altcha-Verifier, Redis-Client) werden lazy auf `app.state` gecacht und aus den injizierten
`Settings` gebaut → in Tests via `dependency_overrides` ersetzbar.

Bewusst als Dependencies (nicht Middleware): so bleibt die Drosselung pro Route
konfigurierbar (api.md §7) und taucht sauber im OpenAPI-Contract auf.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from app.deps import (
    Applicant,
    Principal,
    get_current_applicant,
    get_current_principal,
)
from app.settings import Settings, get_settings
from app.shared.altcha import (
    AltchaError,
    AltchaVerifier,
    NullAltchaVerifier,
    RedisReplayGuard,
)
from app.shared.errors import BadRequestError, PayloadTooLargeError, RateLimitedError
from app.shared.ratelimit import (
    NullRateLimiter,
    RateLimiter,
    RedisRateLimiter,
)

SettingsDep = Annotated[Settings, Depends(get_settings)]
_HOUR = 3600


def client_ip(request: Request) -> str:
    """Client-IP für den Rate-Limit-Schlüssel.

    Hinter dem Reverse-Proxy liefert uvicorn `--proxy-headers` (security.md §3) bereits
    die echte IP in `request.client.host` (X-Forwarded-For nur von vertrauenswürdigen
    Proxys, `FORWARDED_ALLOW_IPS`). Daher hier **kein** ungeprüftes Header-Parsing."""
    return request.client.host if request.client is not None else "unknown"


# --------------------------------------------------------------------------- #
# Provider (lazy, auf app.state gecacht — in Tests überschreibbar)
# --------------------------------------------------------------------------- #
def _redis_client(request: Request, settings: Settings) -> object:
    state = request.app.state
    client = getattr(state, "_antiabuse_redis", None)
    if client is None:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        state._antiabuse_redis = client
    return client


def get_rate_limiter(request: Request, settings: SettingsDep) -> RateLimiter:
    state = request.app.state
    limiter = getattr(state, "_rate_limiter", None)
    if limiter is None:
        limiter = (
            RedisRateLimiter(_redis_client(request, settings))
            if settings.rate_limit_enabled
            else NullRateLimiter()
        )
        state._rate_limiter = limiter
    return limiter


def get_altcha_verifier(
    request: Request, settings: SettingsDep
) -> AltchaVerifier | NullAltchaVerifier:
    state = request.app.state
    verifier = getattr(state, "_altcha_verifier", None)
    if verifier is None:
        if settings.altcha_enabled:
            assert settings.altcha_hmac_secret is not None
            guard = RedisReplayGuard(_redis_client(request, settings))
            verifier = AltchaVerifier(
                settings.altcha_hmac_secret,
                replay=guard,
                replay_ttl_seconds=settings.altcha_challenge_ttl_seconds,
            )
        else:
            verifier = NullAltchaVerifier()
        state._altcha_verifier = verifier
    return verifier


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
AltchaDep = Annotated["AltchaVerifier | NullAltchaVerifier", Depends(get_altcha_verifier)]


# --------------------------------------------------------------------------- #
# Body-Cap (413) — Content-Length-Schranke + gekapptes Lesen (anti-DoS)
# --------------------------------------------------------------------------- #
def body_cap(limit_attr: str) -> Callable[[Request, Settings], None]:
    """Dependency-Factory: 413, wenn `Content-Length` `Settings.<limit_attr>` übersteigt.

    Defense-in-Depth, **nicht** die primäre Schranke: FastAPI puffert den Body, bevor
    Dependencies laufen, und ein `Transfer-Encoding: chunked`-Request hat kein
    `Content-Length` (Review #3). Die maßgebliche Größenschranke gegen unbegrenztes
    Puffern ist daher `client_max_body_size` am Edge-nginx (`deploy/web/nginx.conf`);
    `api` hat keine Host-Ports und ist nur über diesen Proxy erreichbar. Dieser Check
    fängt ehrliche, zu große POSTs früh + billig ab und liefert den konsistenten
    problem+json-413."""

    def dependency(request: Request, settings: SettingsDep) -> None:
        limit = int(getattr(settings, limit_attr))
        raw = request.headers.get("content-length")
        if raw is not None and raw.isdigit() and int(raw) > limit:
            raise PayloadTooLargeError(f"Request body exceeds {limit} bytes.")

    return dependency


enforce_auth_payload_limit = body_cap("max_auth_payload_bytes")
enforce_application_payload_limit = body_cap("max_application_payload_bytes")


# --------------------------------------------------------------------------- #
# Rate-Limit (429)
# --------------------------------------------------------------------------- #
async def _enforce(
    limiter: RateLimiter, key: str, *, limit: int, window: int, detail: str
) -> None:
    result = await limiter.hit(key, limit=limit, window_seconds=window)
    if not result.allowed:
        raise RateLimitedError(detail, retry_after=result.retry_after)


async def _json_field(request: Request, field: str) -> str | None:
    """Feld aus dem (gecachten) JSON-Body lesen — defensiv, ohne hier zu validieren."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — kaputter Body → Endpoint-Validierung übernimmt
        return None
    if isinstance(body, dict):
        value = body.get(field)
        if isinstance(value, str):
            return value
    return None


async def rate_limit_magic_link(
    request: Request, settings: SettingsDep, limiter: RateLimiterDep
) -> None:
    """`POST /auth/magic-link`: 5/Std/IP + 3/Std/Mail (api.md §7)."""
    await _enforce(
        limiter,
        f"magic-link:ip:{client_ip(request)}",
        limit=settings.rl_magic_link_ip_per_hour,
        window=_HOUR,
        detail="Too many magic-link requests from this IP. Try again later.",
    )
    email = await _json_field(request, "email")
    if email:
        await _enforce(
            limiter,
            f"magic-link:mail:{email.lower()}",
            limit=settings.rl_magic_link_mail_per_hour,
            window=_HOUR,
            detail="Too many magic-link requests for this address. Try again later.",
        )


async def rate_limit_magic_link_verify(
    request: Request, settings: SettingsDep, limiter: RateLimiterDep
) -> None:
    """`POST /auth/magic-link/verify`: IP-Limit (Token hochentropisch → großzügig)."""
    await _enforce(
        limiter,
        f"magic-link-verify:ip:{client_ip(request)}",
        limit=settings.rl_magic_link_verify_ip_per_hour,
        window=_HOUR,
        detail="Too many verification attempts from this IP. Try again later.",
    )


async def rate_limit_applications(
    request: Request, settings: SettingsDep, limiter: RateLimiterDep
) -> None:
    """`POST /applications`: 10/Std/IP (api.md §7)."""
    await _enforce(
        limiter,
        f"applications:ip:{client_ip(request)}",
        limit=settings.rl_applications_ip_per_hour,
        window=_HOUR,
        detail="Too many application submissions from this IP. Try again later.",
    )


async def rate_limit_attachments(
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> None:
    """`POST /attachments`: 30/Std/applicant (api.md §7).

    Schlüssel folgt der Identität: Principal-``sub`` bzw. (Antragsteller) die gebundene
    ``application_id``; ohne Identität IP-Fallback. Die Auth-Dependency (401/403) läuft
    separat — dieser Check drosselt nur die Frequenz."""
    if principal is not None:
        key = f"attachments:principal:{principal.sub}"
    elif applicant is not None:
        key = f"attachments:applicant:{applicant.application_id}"
    else:
        key = f"attachments:ip:{client_ip(request)}"
    await _enforce(
        limiter,
        key,
        limit=settings.rl_attachments_per_hour,
        window=_HOUR,
        detail="Too many uploads. Try again later.",
    )


# --------------------------------------------------------------------------- #
# Altcha (400)
# --------------------------------------------------------------------------- #
def require_altcha(field: str = "altcha") -> Callable[..., Awaitable[None]]:
    """Dependency-Factory: verifiziert das Altcha-Solution-Feld aus dem JSON-Body.

    Fehlend/ungültig/abgelaufen/wiederverwendet → 400. Ist Altcha aus (kein Secret),
    liefert `get_altcha_verifier` den No-op-Verifier → Durchlass."""

    async def dependency(request: Request, verifier: AltchaDep) -> None:
        solution = await _json_field(request, field)
        try:
            await verifier.verify(solution)
        except AltchaError as exc:
            raise BadRequestError(
                "Altcha verification failed.", code="altcha_failed"
            ) from exc

    return dependency


verify_altcha = require_altcha()


def require_altcha_unless_authenticated(
    field: str = "altcha",
) -> Callable[..., Awaitable[None]]:
    """Wie :func:`require_altcha`, **überspringt** Altcha aber für eingeloggte Nutzer:innen.

    Begründung (#24): eine gültige Principal-Session ist bereits ein Vertrauensanker —
    Altcha (Bot-/Spam-Abwehr) ist nur für die anonyme öffentliche Einreichung nötig.
    Anonyme Requests durchlaufen die normale Altcha-Prüfung (400 bei fehlend/ungültig).
    """

    inner = require_altcha(field)

    async def dependency(
        request: Request,
        verifier: AltchaDep,
        principal: Annotated[Principal | None, Depends(get_current_principal)],
    ) -> None:
        if principal is not None:
            return
        await inner(request=request, verifier=verifier)

    return dependency


verify_altcha_unless_authenticated = require_altcha_unless_authenticated()


def now_unix() -> int:
    return int(time.time())
