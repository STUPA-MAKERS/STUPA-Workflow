"""TDD: Security-Härtung (T-41, security.md §3/§8/§10).

Deckt die T-41-Akzeptanzkriterien als Unit-Tests ab:
- CSRF (Double-Submit) erzwungen für cookie-authentifizierte schreibende Requests.
- Default-Rate-Limit auf schreibenden Endpunkten → 429 + `Retry-After`.
- X-Forwarded-For wird im App-Code **nicht** geparst (Spoof-Schutz; echte IP kommt
  von uvicorn `--proxy-headers`).
- `FORWARDED_ALLOW_IPS="*"` ist in `production` verboten.
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


# --------------------------------------------------------------------------- #
# CSRF (security.md §10)
# --------------------------------------------------------------------------- #
def test_csrf_write_without_auth_cookie_allowed() -> None:
    """Ohne Auth-Cookie ist nichts zu schützen → Durchlass (z. B. öffentliche POSTs)."""
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
    """Bearer-Token-Requests sind nicht CSRF-fähig → ausgenommen, auch mit Cookie."""
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
    """Regression: BE-Defaults = Angular-Default-Namen, sonst 403 auf jedem SPA-Write.

    Der FE-Interceptor (frontend/.../auth.interceptor.ts) liest Cookie `XSRF-TOKEN` und
    sendet Header `X-XSRF-TOKEN`. Hier den ECHTEN Flow nachstellen: Cookie gesetzt +
    Header gespiegelt → 2xx; ohne Header → 403."""
    s = _settings()
    assert s.csrf_cookie_name == "XSRF-TOKEN"
    assert s.csrf_header_name == "X-XSRF-TOKEN"
    client = _csrf_app(s)
    client.cookies.set(s.session_cookie_name, "sess")
    client.cookies.set("XSRF-TOKEN", "fe-token")
    assert client.post("/w", headers={"X-XSRF-TOKEN": "fe-token"}).status_code == 200
    assert client.post("/w").status_code == 403  # FE würde ohne Token nie schreiben


# --------------------------------------------------------------------------- #
# Default-Rate-Limit auf schreibenden Endpunkten (api.md §7)
# --------------------------------------------------------------------------- #
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
    assert client.post("/w").status_code == 200  # 1. erlaubt
    resp = client.post("/w")  # 2. → 429
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["code"] == "rate_limited"
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_default_write_limit_noop_for_safe_method() -> None:
    s = _settings(rl_default_write_per_hour=1)
    client = _wlimit_app(s, InMemoryRateLimiter())
    for _ in range(5):  # über dem Limit, aber GET → nie gedrosselt
        assert client.get("/r").status_code == 200


# --------------------------------------------------------------------------- #
# Proxy-Trust / X-Forwarded-Spoof (security.md §3)
# --------------------------------------------------------------------------- #
def test_client_ip_ignores_x_forwarded_for() -> None:
    """`client_ip` parst **kein** X-Forwarded-For: gespoofter Header ändert den Key nicht.

    Die echte Client-IP setzt uvicorn `--proxy-headers` aus vertrauenswürdiger Quelle
    in `request.client` — Header-Parsing im App-Code wäre der Spoof-Vektor."""
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


# --------------------------------------------------------------------------- #
# Proxy-Wildcard in production verboten (security.md §3)
# --------------------------------------------------------------------------- #
def test_wildcard_forwarded_allow_ips_rejected_in_production() -> None:
    with pytest.raises(SettingsError):
        _settings(environment="production", forwarded_allow_ips="*")


def test_wildcard_forwarded_allow_ips_allowed_outside_production() -> None:
    s = _settings(environment="development", forwarded_allow_ips="*")
    assert s.forwarded_allow_ips == "*"
