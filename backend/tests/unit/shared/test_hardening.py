"""Security hardening (T-41, security.md §3/§8/§10).

These unit tests cover the T-41 acceptance criteria.
The CSRF double-submit check applies to every cookie-authenticated write request.
The default rate limit on a write endpoint answers 429 plus `Retry-After`.
The app code does NOT parse X-Forwarded-For, which blocks spoofing.
Uvicorn `--proxy-headers` delivers the real client IP.
`FORWARDED_ALLOW_IPS="*"` is forbidden in `production`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.middleware import (
    CsrfMiddleware,
    DefaultWriteRateLimitMiddleware,
    RequestContextMiddleware,
)
from app.settings import Settings, SettingsError, load_settings
from app.shared.antiabuse import client_ip
from app.shared.ratelimit import InMemoryRateLimiter


def _settings(**over: object) -> Settings:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="session-secret-0123",
        magic_link_secret="magic-link-secret-0",
        **over,
    )


def _csrf_app(settings: Settings) -> TestClient:
    app = FastAPI()
    app.add_middleware(CsrfMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)

    @app.post("/w")
    def _w() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/r")
    def _r() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


# CSRF double-submit checks, see security.md §10.
def test_csrf_write_without_auth_cookie_allowed() -> None:
    """A write without an auth cookie has nothing to protect, so it passes (public POST)."""
    s = _settings()
    assert _csrf_app(s).post("/w").status_code == 200


def test_csrf_write_with_session_cookie_no_token_forbidden() -> None:
    s = _settings()
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    resp = client.post("/w")
    assert resp.status_code == 403
    assert resp.json()["code"] == "csrf_failed"
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_csrf_write_with_matching_token_allowed() -> None:
    s = _settings()
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    client.cookies.set(s.csrf_cookie_name, "tok")
    resp = client.post("/w", headers={s.csrf_header_name: "tok"})
    assert resp.status_code == 200


def test_csrf_write_with_mismatched_token_forbidden() -> None:
    s = _settings()
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    client.cookies.set(s.csrf_cookie_name, "tok")
    resp = client.post("/w", headers={s.csrf_header_name: "other"})
    assert resp.status_code == 403


def test_csrf_bearer_request_exempt() -> None:
    """CSRF cannot forge a Bearer-token request, so it stays exempt even with a cookie."""
    s = _settings()
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    resp = client.post("/w", headers={"Authorization": "Bearer abc"})
    assert resp.status_code == 200


def test_csrf_cookie_issued_on_safe_request() -> None:
    s = _settings(cookie_secure=False)
    resp = _csrf_app(s).get("/r")
    assert resp.status_code == 200
    assert s.csrf_cookie_name in resp.cookies


def test_csrf_disabled_skips_enforcement() -> None:
    s = _settings(csrf_enabled=False)
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    assert client.post("/w").status_code == 200


def test_csrf_defaults_match_angular_fe_flow() -> None:
    """Regression: the backend defaults must match the Angular default names.

    A mismatch gives 403 on every write of the SPA. The frontend interceptor
    (frontend/.../auth.interceptor.ts) reads the cookie `XSRF-TOKEN` and sends the
    header `X-XSRF-TOKEN`. This test replays the real flow. The cookie plus the
    mirrored header returns 2xx. The cookie without the header returns 403.
    """
    s = _settings()
    assert s.csrf_cookie_name == "XSRF-TOKEN"
    assert s.csrf_header_name == "X-XSRF-TOKEN"
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    client.cookies.set("XSRF-TOKEN", "fe-token")
    assert client.post("/w", headers={"X-XSRF-TOKEN": "fe-token"}).status_code == 200
    assert client.post("/w").status_code == 403  # the FE never writes without a token


# Default rate limit on write endpoints (api.md §7)
def _wlimit_app(settings: Settings, limiter: InMemoryRateLimiter) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        DefaultWriteRateLimitMiddleware, settings=settings, limiter=limiter
    )
    app.add_middleware(RequestContextMiddleware)

    @app.post("/w")
    def _w() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/r")
    def _r() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_default_write_limit_blocks_second_with_retry_after() -> None:
    s = _settings(rl_default_write_per_hour=1)
    client = _wlimit_app(s, InMemoryRateLimiter())
    assert client.post("/w").status_code == 200  # the first write passes
    resp = client.post("/w")  # the second write gives 429
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["code"] == "rate_limited"
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_default_write_limit_noop_for_safe_method() -> None:
    s = _settings(rl_default_write_per_hour=1)
    client = _wlimit_app(s, InMemoryRateLimiter())
    for _ in range(5):  # over the limit, but a GET is never throttled
        assert client.get("/r").status_code == 200


# Proxy trust and X-Forwarded spoofing (security.md §3)
def test_client_ip_ignores_x_forwarded_for() -> None:
    """`client_ip` parses no X-Forwarded-For, so a spoofed header cannot change the key.

    Uvicorn `--proxy-headers` writes the real client IP into `request.client` from a
    trusted source. Header parsing inside the app code would open the spoof vector.
    """
    req = Request(
        {
            "type": "http",
            "method": "POST",
            "headers": [(b"x-forwarded-for", b"9.9.9.9")],
            "client": ("1.2.3.4", 0),
            "query_string": b"",
        }
    )
    assert client_ip(req) == "1.2.3.4"


# The proxy wildcard is forbidden in production (security.md §3)
def test_wildcard_forwarded_allow_ips_rejected_in_production() -> None:
    with pytest.raises(SettingsError):
        _settings(environment="production", forwarded_allow_ips="*")


def test_wildcard_forwarded_allow_ips_allowed_outside_production() -> None:
    s = _settings(environment="development", forwarded_allow_ips="*")
    assert s.forwarded_allow_ips == "*"
