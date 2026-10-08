"""HTTP middleware: trace id, security headers, CSRF, default write rate limit.

- `RequestContextMiddleware`: per-request trace id (`request.state` + `X-Trace-Id`).
- `SecurityHeadersMiddleware`: base hardening headers. The app serves JSON only, so
  the CSP is a strict `default-src 'none'`. The edge nginx gives the SPA its own
  CSP. The TLS-terminating proxy sets HSTS.
- `CsrfMiddleware`: double-submit token for cookie-authenticated write requests.
  A bearer-token request is not CSRF-able and stays exempt. A request without an
  auth cookie stays exempt too. The token is a non-HttpOnly cookie that the
  frontend mirrors into the `X-CSRF-Token` header.

The app registers no CORSMiddleware on purpose. Cross-origin access stays off.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.modules.auth.sessions import principal_sid
from app.settings import Settings, get_settings
from app.shared.antiabuse import client_ip, get_rate_limiter
from app.shared.errors import PUBLIC_API_PREFIX
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
# The public meeting routes (#17). They apply their own rate limits.
PUBLIC_MEETING_PREFIX = "/api/public/meetings/"

Dispatch = Callable[[Request], Awaitable[Response]]


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        trace_id = uuid.uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers[TRACE_HEADER] = trace_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add the default API headers that the route did not set itself.

    A route can replace a default on purpose: the inline attachment preview sets its
    own CSP and ``X-Frame-Options: SAMEORIGIN`` (see `app.modules.files.router`).
    """

    async def dispatch(self, request: Request, call_next: Dispatch) -> Response:
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith(PUBLIC_API_PREFIX):
            # The public routes (protocols page, QR join) are never for search
            # engines: every answer, an error included, carries noindex.
            response.headers["X-Robots-Tag"] = "noindex"
        return response


def _has_auth_cookie(request: Request, settings: Settings) -> bool:
    """Return True when the request carries an auth cookie (session or applicant).

    Only those requests are CSRF-relevant. The browser sends a cookie cross-site
    on its own. A bearer token is not CSRF-able, so this function ignores it.
    """
    return bool(
        request.cookies.get(settings.session_cookie_name)
        or request.cookies.get(settings.applicant_cookie_name)
        or request.cookies.get(settings.guest_cookie_name)
    )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection.

    For an unsafe method with an auth cookie and no bearer header, the
    `X-CSRF-Token` header must match the CSRF cookie. The compare runs in constant
    time. The middleware sets the CSRF cookie on any response that lacks it, so the
    frontend can mirror it.
    """

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

        # Issue the CSRF cookie when it is missing. It is non-HttpOnly because the
        # frontend must read it. SameSite=Lax gives base protection. Secure follows
        # the auth cookies.
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


def _write_bucket(request: Request, settings: Settings) -> tuple[str, int]:
    """Return the rate-limit key and the limit for a write request.

    Returns:
        The session key with the session limit for a signed principal session
        cookie, else the IP key with the IP limit.
    """
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        sid = principal_sid(
            settings.session_secret, cookie, settings.session_ttl_hours * 3600
        )
        if sid is not None:
            return f"write:session:{sid}", settings.rl_default_write_session_per_hour
    return f"write:ip:{client_ip(request)}", settings.rl_default_write_per_hour


class DefaultWriteRateLimitMiddleware(BaseHTTPMiddleware):
    """Default rate limit for all write endpoints.

    The limit applies only to unsafe methods. It is the backstop for an endpoint
    without its own stricter limit. A request with a principal session cookie that
    has a valid signature keys on that session (`rl_default_write_session_per_hour`),
    because a campus NAT puts all users behind one IP. Any other request keys on the
    client IP (`rl_default_write_per_hour`). Only the server can sign a cookie, so a
    made-up cookie falls back to the IP key and cannot open a new bucket.
    The app adds it as middleware, so it runs for every HTTP route. A WebSocket
    scope passes through, because BaseHTTPMiddleware forwards a non-http scope.
    The middleware answers 429 with `Retry-After` as problem+json. With rate
    limiting off, the builder returns a no-op limiter.
    """

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
        # The public meeting routes (#17) carry their own limits per IP, per join code
        # and per guest. Many guests often share one IP, and the default limit per IP
        # would stop a meeting in the middle of a vote.
        exempt = str(request.scope.get("path", "")).startswith(PUBLIC_MEETING_PREFIX)
        if request.method not in _SAFE_METHODS and not exempt:
            limiter = self._limiter or get_rate_limiter(request, settings)
            key, limit = _write_bucket(request, settings)
            result = await limiter.hit(key, limit=limit, window_seconds=_HOUR)
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
                        "detail": "Too many write requests. Try again later.",
                        "traceId": trace_id,
                    },
                )
        return await call_next(request)
