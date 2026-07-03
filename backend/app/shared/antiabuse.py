"""Anti-abuse wiring for public endpoints.

FastAPI dependencies that enforce a body cap (413), rate limits (429 +
``Retry-After``), and Altcha verification (400) before the endpoint logic runs.
Backends (rate limiter, Altcha verifier, Redis client) are lazily cached on
``app.state`` and built from the injected ``Settings``, so tests can replace them via
``dependency_overrides``.

Deliberately dependencies, not middleware: throttling stays configurable per route
and shows up cleanly in the OpenAPI contract.
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
    """Client IP for the rate-limit key.

    Behind the reverse proxy, uvicorn ``--proxy-headers`` already yields the real IP in
    ``request.client.host`` (X-Forwarded-For only from trusted proxies via
    ``FORWARDED_ALLOW_IPS``), so no unchecked header parsing here."""
    return request.client.host if request.client is not None else "unknown"


# --- Providers (lazy, cached on app.state; overridable in tests) ---
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


# --- Body cap (413) ---
def body_cap(limit_attr: str) -> Callable[[Request, Settings], None]:
    """Dependency factory: 413 if ``Content-Length`` exceeds ``Settings.<limit_attr>``.

    Defense in depth, not the primary limit: FastAPI buffers the body before
    dependencies run, and a chunked request has no ``Content-Length``. The authoritative
    size limit is nginx ``client_max_body_size`` at the edge; ``api`` has no host ports
    and is only reachable through that proxy. This check rejects honest oversized POSTs
    early and cheaply with a consistent problem+json 413."""

    def dependency(request: Request, settings: SettingsDep) -> None:
        limit = int(getattr(settings, limit_attr))
        raw = request.headers.get("content-length")
        if raw is not None and raw.isdigit() and int(raw) > limit:
            raise PayloadTooLargeError(f"Request body exceeds {limit} bytes.")

    return dependency


enforce_auth_payload_limit = body_cap("max_auth_payload_bytes")
enforce_application_payload_limit = body_cap("max_application_payload_bytes")


# --- Rate limit (429) ---
async def _enforce(
    limiter: RateLimiter, key: str, *, limit: int, window: int, detail: str
) -> None:
    result = await limiter.hit(key, limit=limit, window_seconds=window)
    if not result.allowed:
        raise RateLimitedError(detail, retry_after=result.retry_after)


def _is_oauth_principal(principal: Principal | None) -> bool:
    """Authenticated via an OAuth access token (MCP)?

    Only the OAuth grant path sets ``scope_permissions`` (gated on ``mcp.use`` at
    consent); browser sessions leave it ``None``. The logged-in MCP is a trusted
    first-party client, so frequency throttles are skipped for it."""
    return principal is not None and principal.scope_permissions is not None


def canonical_mail_key(email: str) -> str:
    """Canonical form of an email for the per-mail rate-limit key.

    Folds variants that deliver to the same mailbox onto one key so the per-mail limit
    cannot be bypassed by address normalization:

    - ``strip()`` + NFC normalization against unicode/whitespace variants,
    - domain casefolded (case-insensitive, IDN-friendly),
    - local part casefolded and the provider plus-tag removed
      (``victim+1@host`` -> ``victim@host``).

    Purely for the throttle key, not address validation (the endpoint does that via
    ``EmailStr``)."""
    normalized = unicodedata.normalize("NFC", email).strip()
    local, sep, domain = normalized.rpartition("@")
    if not sep:  # no '@'; endpoint validation rejects this anyway
        return normalized.casefold()
    local = local.split("+", 1)[0]
    return f"{local.casefold()}@{domain.casefold()}"


async def _json_field(request: Request, field: str) -> str | None:
    """Read a field from the (cached) JSON body defensively, without validating here."""
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
    """``POST /auth/magic-link``: 5/h/IP + 3/h/mail."""
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
    """``POST /auth/magic-link/verify``: IP limit (high-entropy token, so generous)."""
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

    The key follows identity: principal ``sub`` or (applicant) the bound
    ``application_id``, falling back to IP without identity. The auth dependency
    (401/403) runs separately; this only throttles frequency."""
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

    Throttles FinTS sync as an SSRF port-scan oracle and repeated bank logins
    (PIN-lockout abuse). The auth dependency (401/403) runs separately; this only
    throttles frequency."""
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


# --- Altcha (400) ---
def require_altcha(field: str = "altcha") -> Callable[..., Awaitable[None]]:
    """Dependency factory: verify the Altcha solution field from the JSON body.

    Missing/invalid/expired/reused -> 400. When Altcha is off (no secret),
    ``get_altcha_verifier`` returns the no-op verifier and requests pass through."""

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
    """Like :func:`require_altcha`, but skips Altcha for logged-in users.

    A valid principal session is already a trust anchor; Altcha (bot/spam defense) is
    only needed for anonymous public submission. Anonymous requests go through the
    normal Altcha check (400 if missing/invalid).
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
