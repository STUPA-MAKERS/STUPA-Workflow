"""Anti-abuse wiring: dependencies, providers and the challenge endpoint (Issues #23/#24)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.main import create_app, lifespan
from app.middleware import RequestContextMiddleware
from app.settings import Settings, load_settings
from app.shared.altcha import AltchaVerifier, InMemoryReplayGuard, create_challenge, solve_challenge
from app.shared.antiabuse import (
    canonical_mail_key,
    client_ip,
    enforce_auth_payload_limit,
    get_altcha_verifier,
    get_rate_limiter,
    now_unix,
    rate_limit_applications,
    rate_limit_fints,
    rate_limit_magic_link,
    verify_altcha,
)
from app.shared.errors import RateLimitedError
from app.shared.ratelimit import InMemoryRateLimiter, NullRateLimiter, RedisRateLimiter

ALTCHA_SECRET = "altcha-test-secret-0123"


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x/y",
        "session_secret": "session-secret-0123",
        "magic_link_secret": "magic-link-secret-0",
    }
    base.update(over)
    return load_settings(**base)


def test_client_ip_from_request() -> None:
    req = SimpleNamespace(client=SimpleNamespace(host="9.9.9.9"))
    assert client_ip(req) == "9.9.9.9"  # type: ignore[arg-type]


def test_client_ip_unknown_when_no_client() -> None:
    assert client_ip(SimpleNamespace(client=None)) == "unknown"  # type: ignore[arg-type]


def test_now_unix_is_int() -> None:
    assert isinstance(now_unix(), int)


def test_get_rate_limiter_null_when_disabled() -> None:
    settings = _settings(rate_limit_enabled=False)
    app = create_app(settings)
    req = SimpleNamespace(app=app)
    limiter = get_rate_limiter(req, settings)  # type: ignore[arg-type]
    assert isinstance(limiter, NullRateLimiter)
    assert get_rate_limiter(req, settings) is limiter  # type: ignore[arg-type]


def test_get_rate_limiter_redis_when_enabled() -> None:
    settings = _settings(rate_limit_enabled=True)
    app = create_app(settings)
    req = SimpleNamespace(app=app)
    assert isinstance(get_rate_limiter(req, settings), RedisRateLimiter)  # type: ignore[arg-type]


def test_get_altcha_verifier_null_without_secret() -> None:
    settings = _settings()
    app = create_app(settings)
    req = SimpleNamespace(app=app)
    verifier = get_altcha_verifier(req, settings)  # type: ignore[arg-type]
    assert type(verifier).__name__ == "NullAltchaVerifier"


def test_get_altcha_verifier_real_with_secret() -> None:
    settings = _settings(altcha_hmac_secret=ALTCHA_SECRET)
    app = create_app(settings)
    req = SimpleNamespace(app=app)
    assert isinstance(get_altcha_verifier(req, settings), AltchaVerifier)  # type: ignore[arg-type]


def _app(
    *, settings: Settings, limiter: object | None = None, verifier: object | None = None
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    from app.settings import get_settings
    from app.shared.errors import register_exception_handlers

    register_exception_handlers(app)
    app.dependency_overrides[get_settings] = lambda: settings
    if limiter is not None:
        app.dependency_overrides[get_rate_limiter] = lambda: limiter
    if verifier is not None:
        app.dependency_overrides[get_altcha_verifier] = lambda: verifier

    @app.post("/ml", dependencies=[Depends(rate_limit_magic_link)])
    def ml(body: dict[str, object]) -> dict[str, str]:
        return {"ok": "ml"}

    @app.post("/apps", dependencies=[Depends(rate_limit_applications)])
    def apps() -> dict[str, str]:
        return {"ok": "apps"}

    @app.post("/altcha", dependencies=[Depends(verify_altcha)])
    def altcha() -> dict[str, str]:
        return {"ok": "altcha"}

    @app.post("/cap", dependencies=[Depends(enforce_auth_payload_limit)])
    def cap() -> dict[str, str]:
        return {"ok": "cap"}

    return app


def test_payload_cap_413() -> None:
    client = TestClient(_app(settings=_settings(max_auth_payload_bytes=10)))
    resp = client.post("/cap", headers={"content-length": "999"}, content=b"x" * 999)
    assert resp.status_code == 413
    assert resp.headers["content-type"].startswith("application/problem+json")


def test_rate_limit_ip_blocks_with_retry_after() -> None:
    settings = _settings(rl_magic_link_ip_per_hour=5, rl_magic_link_mail_per_hour=99)
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    client = TestClient(_app(settings=settings, limiter=limiter))
    # Every request uses a different mail, so only the IP limit of 5 applies.
    for i in range(5):
        assert client.post("/ml", json={"email": f"u{i}@x.de"}).status_code == 200
    blocked = client.post("/ml", json={"email": "u9@x.de"})
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) >= 1


def test_rate_limit_mail_blocks() -> None:
    settings = _settings(rl_magic_link_ip_per_hour=99, rl_magic_link_mail_per_hour=3)
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    client = TestClient(_app(settings=settings, limiter=limiter))
    for _ in range(3):
        assert client.post("/ml", json={"email": "same@x.de"}).status_code == 200
    blocked = client.post("/ml", json={"email": "same@x.de"})
    assert blocked.status_code == 429


def test_canonical_mail_key_folds_variants() -> None:
    # Plus tags, letter case and whitespace fold to the same key (AUD-026).
    base = canonical_mail_key("victim@gmail.com")
    assert canonical_mail_key("victim+1@gmail.com") == base
    assert canonical_mail_key("victim+anything.else@gmail.com") == base
    assert canonical_mail_key("VICTIM@GMAIL.COM") == base
    assert canonical_mail_key("  victim@gmail.com  ") == base
    assert canonical_mail_key("other@gmail.com") != base
    assert canonical_mail_key("NoAt") == "noat"


def test_rate_limit_mail_blocks_across_plus_tag_variants() -> None:
    settings = _settings(rl_magic_link_ip_per_hour=99, rl_magic_link_mail_per_hour=3)
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    client = TestClient(_app(settings=settings, limiter=limiter))
    variants = ["victim@x.de", "victim+1@x.de", "VICTIM@x.de"]
    for i in range(3):
        assert client.post("/ml", json={"email": variants[i]}).status_code == 200
    blocked = client.post("/ml", json={"email": "victim+spam@x.de"})
    assert blocked.status_code == 429


def test_rate_limit_skips_mail_when_absent() -> None:
    settings = _settings(rl_magic_link_ip_per_hour=99, rl_magic_link_mail_per_hour=1)
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    client = TestClient(_app(settings=settings, limiter=limiter))
    # A missing or invalid mail field skips the mail limit, so no 429 follows.
    assert client.post("/ml", json={"email": 123}).status_code == 200
    assert client.post("/ml", json={"nope": "x"}).status_code == 200


def test_applications_rate_limit_blocks() -> None:
    settings = _settings(rl_applications_ip_per_hour=2)
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    client = TestClient(_app(settings=settings, limiter=limiter))
    assert client.post("/apps").status_code == 200
    assert client.post("/apps").status_code == 200
    assert client.post("/apps").status_code == 429


async def test_rate_limit_fints_bypassed_for_oauth_principal() -> None:
    """A logged-in MCP client bypasses the FinTS throttle (#mcp).

    An OAuth token sets `scope_permissions` on the principal, which marks it as an
    agent. A session principal leaves `scope_permissions` at None and stays throttled.
    """
    import pytest

    from app.modules.auth.principal import Principal

    settings = _settings(rl_fints_per_hour=0)  # blocks every throttled caller
    limiter = InMemoryRateLimiter(now=lambda: 0.0)
    req = SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"), headers={})
    mcp = Principal(sub="u-mcp", scope_permissions=frozenset({"budget.book"}))
    await rate_limit_fints(req, settings, limiter, mcp)  # type: ignore[arg-type]
    session = Principal(sub="u-web")
    with pytest.raises(RateLimitedError):
        await rate_limit_fints(req, settings, limiter, session)  # type: ignore[arg-type]


def test_rate_limit_disabled_never_blocks() -> None:
    settings = _settings(rl_applications_ip_per_hour=1)
    client = TestClient(_app(settings=settings, limiter=NullRateLimiter()))
    for _ in range(5):
        assert client.post("/apps").status_code == 200


def _verifier() -> AltchaVerifier:
    return AltchaVerifier(
        ALTCHA_SECRET, replay=InMemoryReplayGuard(now=lambda: 0), now=lambda: 0
    )


def test_altcha_valid_passes() -> None:
    client = TestClient(_app(settings=_settings(), verifier=_verifier()))
    solution = solve_challenge(create_challenge(ALTCHA_SECRET, max_number=50))
    assert client.post("/altcha", json={"altcha": solution}).status_code == 200


def test_altcha_missing_400() -> None:
    client = TestClient(_app(settings=_settings(), verifier=_verifier()))
    resp = client.post("/altcha", json={})
    assert resp.status_code == 400
    assert resp.json()["code"] == "altcha_failed"


def test_altcha_invalid_400() -> None:
    client = TestClient(_app(settings=_settings(), verifier=_verifier()))
    assert client.post("/altcha", json={"altcha": "garbage"}).status_code == 400


def test_altcha_non_json_body_treated_as_missing() -> None:
    # A broken non-JSON body hides the field. The dependency treats it as missing and
    # answers 400, not 500.
    client = TestClient(_app(settings=_settings(), verifier=_verifier()))
    resp = client.post(
        "/altcha", content=b"not json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400


def test_altcha_replay_400() -> None:
    client = TestClient(_app(settings=_settings(), verifier=_verifier()))
    solution = solve_challenge(create_challenge(ALTCHA_SECRET, max_number=50))
    assert client.post("/altcha", json={"altcha": solution}).status_code == 200
    assert client.post("/altcha", json={"altcha": solution}).status_code == 400


def test_challenge_404_when_disabled() -> None:
    client = TestClient(create_app(_settings()))
    assert client.get("/api/altcha/challenge").status_code == 404


def test_challenge_returns_solvable_challenge() -> None:
    settings = _settings(altcha_hmac_secret=ALTCHA_SECRET, altcha_max_number=200)
    app = create_app(settings)
    from app.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)
    body = client.get("/api/altcha/challenge").json()
    assert body["algorithm"] == "SHA-256"
    assert body["maxnumber"] == 200
    from app.shared.altcha import Challenge, solve_challenge, verify_solution

    challenge = Challenge(**body)
    verify_solution(solve_challenge(challenge), ALTCHA_SECRET, now=0)


# The real routers enforce ALTCHA (Issue #23) before they touch the database or start
# a background task.
def test_magic_link_router_rejects_missing_altcha() -> None:
    settings = _settings(altcha_hmac_secret=ALTCHA_SECRET)
    app = create_app(settings)
    from app.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_altcha_verifier] = lambda: _verifier()
    resp = TestClient(app).post("/api/auth/magic-link", json={"email": "a@b.de"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "altcha_failed"


def test_applications_router_rejects_missing_altcha() -> None:
    settings = _settings(altcha_hmac_secret=ALTCHA_SECRET)
    app = create_app(settings)
    from app.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_altcha_verifier] = lambda: _verifier()
    resp = TestClient(app).post(
        "/api/applications",
        json={
            "typeId": "11111111-1111-1111-1111-111111111111",
            "data": {},
            "applicantEmail": "a@b.de",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "altcha_failed"


# The format check of the altcha field runs BEFORE the logic and stays active even when
# the verification switch is off. Contract `negative_data_rejection` requires a 4xx for a
# malformed payload (Issue #23).
#
# Exact CI reproduction: this control-character string negated the `null` variant of the
# `anyOf[string,null]` schema but still counted as a string, so the endpoint answered 202.
_MALFORMED_ALTCHA = "ZÈ♯æL¾&"


def test_magic_link_malformed_altcha_422_even_when_disabled() -> None:
    # Without an ALTCHA secret the verification is off, which matches CI. A structurally
    # invalid payload must still get a 422 in problem+json, not a 202.
    app = create_app(_settings())
    resp = TestClient(app).post(
        "/api/auth/magic-link", json={"email": "a@b.de", "altcha": _MALFORMED_ALTCHA}
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["errors"][0]["field"] == "body.altcha"


def test_applications_malformed_altcha_422_even_when_disabled() -> None:
    app = create_app(_settings())
    resp = TestClient(app).post(
        "/api/applications",
        json={
            "typeId": "11111111-1111-1111-1111-111111111111",
            "data": {},
            "applicantEmail": "a@b.de",
            "altcha": _MALFORMED_ALTCHA,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "body.altcha"


async def test_lifespan_closes_redis_client() -> None:
    app = create_app(_settings())

    class _FakeRedis:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    fake = _FakeRedis()
    app.state._antiabuse_redis = fake
    async with lifespan(app):
        pass
    assert fake.closed
