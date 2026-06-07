"""HTTP-Middleware: Trace-Id + Security-Header + CSRF (security.md §3/§10).

- `RequestContextMiddleware`: vergibt pro Request eine Trace-Id (`request.state`
  + `X-Trace-Id`-Header), nutzbar im Fehler-Contract.
- `SecurityHeadersMiddleware`: setzt Basis-Hardening-Header an der App. Die App liefert
  ausschließlich JSON (kein HTML/JS) → strikte CSP `default-src 'none'`. Die SPA-HTML
  bekommt ihre (lockerere, nonce-fähige) CSP am Edge/`web`-nginx. HSTS setzt der NPM
  (TLS terminiert dort, security.md §3/§10).
- `CsrfMiddleware`: Double-Submit-Token (security.md §10). Schützt cookie-
  authentifizierte **schreibende** Requests (POST/PUT/PATCH/DELETE). Bearer-Token-
  Requests (Authorization-Header) sind nicht CSRF-fähig → ausgenommen; Requests ohne
  Auth-Cookie haben nichts zu schützen → ausgenommen. Der Token wird als nicht-HttpOnly
  Cookie ausgegeben (FE liest + spiegelt ihn im `X-CSRF-Token`-Header).

CORS bewusst **aus** (kein CORSMiddleware) — kein Cross-Origin per Default.
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

# Strikte, für eine reine JSON-API passende CSP: kein aktiver Inhalt erlaubt; in
# `<iframe>` einbetten verboten (Clickjacking). Die SPA-CSP steht im `web`-nginx.
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
    """True, wenn der Request mit einem Auth-**Cookie** kommt (session/applicant).

    Nur solche Requests sind CSRF-relevant: der Browser sendet das Cookie automatisch
    cross-site mit. Bearer-Token im Authorization-Header werden hier nicht erfasst und
    sind ohnehin nicht CSRF-fähig."""
    return bool(
        request.cookies.get(settings.session_cookie_name)
        or request.cookies.get(settings.applicant_cookie_name)
    )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-Submit-CSRF-Schutz (security.md §10).

    Erzwingt bei unsicheren Methoden mit Auth-Cookie und **ohne** Bearer-Header, dass
    `X-CSRF-Token` mit dem CSRF-Cookie übereinstimmt (konstantzeitiger Vergleich). Setzt
    das CSRF-Cookie auf jeder Antwort, falls es fehlt, damit das FE es spiegeln kann."""

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

        # CSRF-Cookie ausstellen, falls es fehlt: nicht-HttpOnly (FE muss es lesen),
        # SameSite=Lax als Basisschutz, Secure analog zu den Auth-Cookies.
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
    """Default-Rate-Limit auf **allen schreibenden** Endpunkten (api.md §7, security.md §8).

    Greift nur bei unsicheren HTTP-Methoden (POST/PUT/PATCH/DELETE), keyed per IP, mit
    großzügigem Limit → fängt Endpunkte ohne eigenes (strengeres) Limit ab. Als Middleware
    (statt Route-Dependency) verdrahtet: läuft uniform für jede HTTP-Route, lässt aber
    WebSocket-Scopes unberührt (BaseHTTPMiddleware reicht non-http durch). 429 +
    `Retry-After` als problem+json. Bei deaktiviertem Rate-Limit liefert der Builder den
    No-op-Limiter → Durchlass."""

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
