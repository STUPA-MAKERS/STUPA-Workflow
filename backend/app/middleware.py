"""HTTP-Middleware: Trace-Id + Security-Header (security.md §3/§10).

- `RequestContextMiddleware`: vergibt pro Request eine Trace-Id (`request.state`
  + `X-Trace-Id`-Header), nutzbar im Fehler-Contract.
- `SecurityHeadersMiddleware`: setzt Basis-Hardening-Header an der App. Strikte CSP
  + HSTS setzt zusätzlich der Edge/`web`-nginx.

CORS bewusst **aus** (kein CORSMiddleware) — kein Cross-Origin per Default.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

TRACE_HEADER = "X-Trace-Id"

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

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
