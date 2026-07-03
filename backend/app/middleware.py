"""HTTP middleware: trace id, security headers, CSRF, default write rate limit.

- `RequestContextMiddleware`: per-request trace id (`request.state` + `X-Trace-Id`).
- `SecurityHeadersMiddleware`: base hardening headers. The app serves JSON only,
  so the CSP is a strict `default-src 'none'`; the SPA gets its own CSP at the
  edge nginx, and HSTS is set by the TLS-terminating proxy.
- `CsrfMiddleware`: double-submit token for cookie-authenticated write requests.
  Bearer-token requests are not CSRF-able and are exempt, as are requests without
  an auth cookie. The token is a non-HttpOnly cookie the frontend mirrors into
  the `X-CSRF-Token` header.

CORS is deliberately off (no CORSMiddleware) — no cross-origin by default.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.settings import Settings, get_settings
from app.shared.antiabuse import client_ip, get_rate_limiter
from app.shared.ratelimit import RateLimiter

TRACE_HEADER = "X-Trace-Id"
PROBLEM_JSON = "application/problem+json"
_HOUR = 3600

# Strict CSP for a pure JSON API: no active content, no framing (clickjacking).
_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": _API_CSP,
}

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

Dispatch = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        trace_id = uuid.uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


def _has_auth_cookie(request: Request, settings: Settings) -> bool:
    """Return True if the request carries an auth cookie (session/applicant).

    Only those requests are CSRF-relevant: the browser sends cookies cross-site
    automatically. Bearer tokens are not CSRF-able and are ignored here."""
    return bool(
        request.cookies.get(settings.session_cookie_name)
        or request.cookies.get(settings.applicant_cookie_name)
    )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection.

    For unsafe methods with an auth cookie and no bearer header, `X-CSRF-Token`
    must match the CSRF cookie (constant-time compare). Sets the CSRF cookie on
    any response that lacks it so the frontend can mirror it."""

    def __init__(self, app: object, settings: Settings | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings or get_settings()

    def _forbid(self, request: Request, detail: str) -> JSONResponse:
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=403,
            media_type=PROBLEM_JSON,
            content={
                "type": "app://error/csrf_failed",
                "title": "Forbidden",
                "status": 403,
                "code": "csrf_failed",
                "detail": detail,
                "traceId": trace_id,
            },
        )

    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        settings = self._settings
        enforce = (
            settings.csrf_enabled
            and request.method not in _SAFE_METHODS
            and not request.headers.get("authorization", "").startswith("Bearer ")
            and _has_auth_cookie(request, settings)
        )
        if enforce:
            cookie = request.cookies.get(settings.csrf_cookie_name)
            header = request.headers.get(settings.csrf_header_name)
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                return self._forbid(request, "CSRF token missing or invalid.")

        response = await call_next(request)

        # Issue the CSRF cookie if missing: non-HttpOnly (frontend must read it),
        # SameSite=Lax as base protection, Secure matching the auth cookies.
        if settings.csrf_enabled and not request.cookies.get(settings.csrf_cookie_name):
            response.set_cookie(
                settings.csrf_cookie_name,
                secrets.token_urlsafe(32),
                max_age=settings.session_ttl_hours * 3600,
                secure=settings.cookie_secure,
                httponly=False,
                samesite="lax",
                path="/",
            )
        return response


class DefaultWriteRateLimitMiddleware(BaseHTTPMiddleware):
    """Default rate limit for all write endpoints.

    Applies only to unsafe methods, keyed per IP, with a generous limit — a
    backstop for endpoints without their own stricter limit. Wired as middleware
    so it runs uniformly for every HTTP route while WebSocket scopes pass through
    (BaseHTTPMiddleware forwards non-http). Responds 429 + `Retry-After` as
    problem+json; with rate limiting disabled the builder yields a no-op limiter."""

    def __init__(
        self,
        app: object,
        settings: Settings | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._settings = settings or get_settings()
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        settings = self._settings
        if request.method not in _SAFE_METHODS:
            limiter = self._limiter or get_rate_limiter(request, settings)
            result = await limiter.hit(
                f"write:ip:{client_ip(request)}",
                limit=settings.rl_default_write_per_hour,
                window_seconds=_HOUR,
            )
            if not result.allowed:
                trace_id = getattr(request.state, "trace_id", None)
                return JSONResponse(
                    status_code=429,
                    media_type=PROBLEM_JSON,
                    headers={"Retry-After": str(max(0, result.retry_after))},
                    content={
                        "type": "app://error/rate_limited",
                        "title": "Too Many Requests",
                        "status": 429,
                        "code": "rate_limited",
                        "detail": "Too many write requests from this IP. Try again later.",
                        "traceId": trace_id,
                    },
                )
        return await call_next(request)
