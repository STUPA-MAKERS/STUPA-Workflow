"""Anti-abuse wiring for public endpoints.

The FastAPI dependencies here run before the endpoint logic. They enforce a body cap
(413), the rate limits (429 with ``Retry-After``) and ALTCHA verification (400). The
backends are the rate limiter, the ALTCHA verifier and the Redis client. The module
builds them from the injected ``Settings`` and caches them lazily on ``app.state``, so
tests can replace them through ``dependency_overrides``.

These are dependencies and not middleware on purpose. Each route can then set its own
throttle, and the OpenAPI contract shows the behavior.
"""

from __future__ import annotations

import time
import unicodedata
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
    """Return the client IP for the rate-limit key.

    Behind the reverse proxy, uvicorn ``--proxy-headers`` puts the real IP into
    ``request.client.host``. It accepts X-Forwarded-For only from the trusted proxies in
    ``FORWARDED_ALLOW_IPS``. This function therefore parses no header itself.
    """
    return request.client.host if request.client is not None else "unknown"


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


def body_cap(limit_attr: str) -> Callable[[Request, Settings], None]:
    """Make a dependency that answers 413 when the request body is too large.

    The dependency compares ``Content-Length`` against ``Settings.<limit_attr>``.

    This is defense in depth and not the primary limit. FastAPI buffers the body before
    the dependencies run, and a chunked request carries no ``Content-Length``. The
    authoritative size limit is nginx ``client_max_body_size`` at the edge. The ``api``
    service has no host ports and is reachable only through that proxy. This check
    rejects an honest oversized POST early and cheaply with a consistent problem+json
    413.
    """

    def dependency(request: Request, settings: SettingsDep) -> None:
        limit = int(getattr(settings, limit_attr))
        raw = request.headers.get("content-length")
        if raw is not None and raw.isdigit() and int(raw) > limit:
            raise PayloadTooLargeError(f"Request body exceeds {limit} bytes.")

    return dependency


enforce_auth_payload_limit = body_cap("max_auth_payload_bytes")
enforce_application_payload_limit = body_cap("max_application_payload_bytes")


async def _enforce(
    limiter: RateLimiter, key: str, *, limit: int, window: int, detail: str
) -> None:
    result = await limiter.hit(key, limit=limit, window_seconds=window)
    if not result.allowed:
        raise RateLimitedError(detail, retry_after=result.retry_after)


def _is_oauth_principal(principal: Principal | None) -> bool:
    """Tell whether an OAuth access token authenticated the principal.

    Only the OAuth grant path sets ``scope_permissions``. Consent gates that path on
    ``mcp.use``. A browser session leaves the field ``None``. The logged-in MCP is a
    trusted first-party client, so the frequency throttles skip it.
    """
    return principal is not None and principal.scope_permissions is not None


def canonical_mail_key(email: str) -> str:
    """Build the canonical form of an email for the per-mail rate-limit key.

    The function folds the variants that reach the same mailbox onto one key. A caller
    then cannot bypass the per-mail limit with a rewritten address. It works in three
    steps:

    1. Strip the value and normalize it to NFC, against unicode and whitespace variants.
    2. Casefold the domain, which is case-insensitive and IDN-friendly.
    3. Casefold the local part and remove the provider plus-tag
       (``victim+1@host`` becomes ``victim@host``).

    The result serves the throttle key only. It does not validate the address. The
    endpoint does that with ``EmailStr``.
    """
    normalized = unicodedata.normalize("NFC", email).strip()
    local, sep, domain = normalized.rpartition("@")
    if not sep:  # no '@'. The endpoint validation rejects this anyway.
        return normalized.casefold()
    local = local.split("+", 1)[0]
    return f"{local.casefold()}@{domain.casefold()}"


async def _json_field(request: Request, field: str) -> str | None:
    """Read a field from the cached JSON body without validating it here.

    Returns:
        The string value. ``None`` when the body or the field is not usable.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - broken body -> endpoint validation handles it
        return None
    if isinstance(body, dict):
        value = body.get(field)
        if isinstance(value, str):
            return value
    return None


async def rate_limit_magic_link(
    request: Request, settings: SettingsDep, limiter: RateLimiterDep
) -> None:
    """Throttle ``POST /auth/magic-link`` to 5/h per IP and 3/h per mail address."""
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
            f"magic-link:mail:{canonical_mail_key(email)}",
            limit=settings.rl_magic_link_mail_per_hour,
            window=_HOUR,
            detail="Too many magic-link requests for this address. Try again later.",
        )


async def rate_limit_magic_link_verify(
    request: Request, settings: SettingsDep, limiter: RateLimiterDep
) -> None:
    """Throttle ``POST /auth/magic-link/verify`` per IP.

    The limit is generous, because the token has high entropy.
    """
    await _enforce(
        limiter,
        f"magic-link-verify:ip:{client_ip(request)}",
        limit=settings.rl_magic_link_verify_ip_per_hour,
        window=_HOUR,
        detail="Too many verification attempts from this IP. Try again later.",
    )


async def rate_limit_applications(
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
) -> None:
    """``POST /applications``: 10/h/IP."""
    if _is_oauth_principal(principal):
        return  # logged-in MCP -> no throttle
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
    """``POST /attachments``: 30/h per applicant.

    The key follows the identity. It uses the principal ``sub``, or the bound
    ``application_id`` of the applicant, or the IP when neither exists. The auth
    dependency (401/403) runs separately. This dependency only throttles the frequency.
    """
    if _is_oauth_principal(principal):
        return  # logged-in MCP -> no throttle
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


async def rate_limit_fints(
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
) -> None:
    """``POST /accounts/*/fints/*`` + ``/statement/import``: per principal/hour.

    The throttle blocks two abuses. An attacker can use the FinTS sync as an SSRF
    port-scan oracle. An attacker can also repeat bank logins to force a PIN lockout.
    The auth dependency (401/403) runs separately. This dependency only throttles the
    frequency.
    """
    if _is_oauth_principal(principal):
        return  # logged-in MCP -> no throttle
    key = (
        f"fints:principal:{principal.sub}"
        if principal is not None
        else f"fints:ip:{client_ip(request)}"
    )
    await _enforce(
        limiter,
        key,
        limit=settings.rl_fints_per_hour,
        window=_HOUR,
        detail="Too many bank-sync requests. Try again later.",
    )


def require_altcha(field: str = "altcha") -> Callable[..., Awaitable[None]]:
    """Dependency factory: verify the ALTCHA solution field from the JSON body.

    A missing, invalid, expired or reused solution gives a 400. When ALTCHA is off (no
    secret), ``get_altcha_verifier`` returns the no-op verifier and the request passes
    through.
    """

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
    """Like ``require_altcha``, but skip ALTCHA for a logged-in user.

    A valid principal session is already a trust anchor. Only an anonymous public
    submission needs ALTCHA, which defends against bots and spam. An anonymous request
    goes through the normal ALTCHA check (400 when the solution is missing or invalid).
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
