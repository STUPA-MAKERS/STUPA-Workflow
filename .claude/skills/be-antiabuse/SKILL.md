---
name: be-antiabuse
description: ALTCHA proof-of-work captcha + sliding-window rate-limiting + body-cap for public/unauthenticated endpoints (magic-link, applications, attachments). Real nouns: GET /api/altcha/challenge, require_altcha, AltchaVerifier, RedisReplayGuard, RedisRateLimiter, body_cap, rate_limit_magic_link, ALTCHA_HMAC_SECRET. Use when working on captcha, rate limits, abuse protection, or public-endpoint hardening in backend/app/modules/antiabuse and backend/app/shared/{altcha,antiabuse,ratelimit}.py.
---

# Anti-Abuse (ALTCHA + rate-limit) — `backend/app/modules/antiabuse`

**Does:** Protects public/unauthenticated endpoints with a self-hosted ALTCHA proof-of-work captcha (no third-party, GDPR-clean), per-IP/mail/identity sliding-window rate-limiting, and a defensive request-body size cap. The module itself only exposes the challenge-issuing route; the enforcement logic lives in `app.shared`.

**Key files:**
- `modules/antiabuse/router.py` — the only router: `GET /altcha/challenge` (mounted under `/api`). Returns 404 when ALTCHA is unconfigured.
- `modules/antiabuse/__init__.py` — package docstring only.
- `shared/altcha.py` — pure ALTCHA crypto: `create_challenge`, `verify_solution`, `parse_solution`/`validate_solution_format`/`AltchaSolutionStr` (422 form-validator), `solve_challenge` (reference solver, tests only), `AltchaVerifier`, `NullAltchaVerifier`, `ReplayGuard`/`InMemoryReplayGuard`/`RedisReplayGuard`, `AltchaError`.
- `shared/antiabuse.py` — FastAPI-dependency wiring: `require_altcha`/`verify_altcha`, `require_altcha_unless_authenticated`, `body_cap` factory (+ `enforce_auth_payload_limit`, `enforce_application_payload_limit`), `rate_limit_magic_link[_verify]`, `rate_limit_applications`, `rate_limit_attachments`, provider getters (`get_rate_limiter`, `get_altcha_verifier`), `client_ip`, `SettingsDep`.
- `shared/ratelimit.py` — `RateLimiter` protocol + `Null`/`InMemory`/`RedisRateLimiter` (ZSET sliding window), `RateLimitResult`.

**Domain / data model:** No DB tables — all state is in Redis with short TTLs.
- **Challenge** (dataclass): `algorithm` (`"SHA-256"`), `challenge` (`SHA-256(salt+number)` hex), `salt` (random + `?expires=<unix>` query encoded in), `signature` (`HMAC-SHA256(secret, challenge)`), `maxnumber`. FE brute-forces `number`, returns base64-JSON **Solution** in the `altcha` body field.
- **Verification** (`verify_solution`, pure, constant-time): checks algorithm, expiry (from salt), hash recompute, HMAC signature; returns the signature as the **replay key**.
- **Replay guard:** Redis `SET NX EX` keyed `altcha:seen:<sig>`. On Redis failure it does **not** fail open — falls back to a per-worker `InMemoryReplayGuard`.
- **Rate-limit:** Redis ZSET (`rl:<key>`), score=timestamp, sliding window. Keys: `magic-link:ip:<ip>`, `magic-link:mail:<email>`, `magic-link-verify:ip:<ip>`, `applications:ip:<ip>`, `attachments:{principal|applicant|ip}:<id>`. Returns `RateLimitResult{allowed, retry_after}`.
- **Config knobs** (`app/settings.py`): `altcha_hmac_secret` (None ⇒ ALTCHA off; `altcha_enabled` derived), `altcha_max_number` (100k), `altcha_challenge_ttl_seconds` (300, doubles as replay TTL); `rate_limit_enabled` (True), `rl_magic_link_ip_per_hour` (5), `rl_magic_link_mail_per_hour` (3), `rl_magic_link_verify_ip_per_hour` (20), `rl_applications_ip_per_hour` (10), `rl_attachments_per_hour` (30), `rl_default_write_per_hour` (100); `max_auth_payload_bytes` (8192), `max_application_payload_bytes` (65536); `redis_url`.

**API surface:**
- `GET /api/altcha/challenge` — issue a fresh HMAC-signed PoW challenge (`AltchaChallengeOut`); 404 (`NotFoundError`) when no `ALTCHA_HMAC_SECRET` is set. Other dependencies here are consumed by *other* modules' routes (auth, applications, attachments) via `Depends`.

**Conventions & gotchas:**
- **Enforcement is via FastAPI Dependencies, not middleware** — so throttling/captcha is per-route, configurable, and shows up in the OpenAPI contract. To protect a new public POST, add the relevant `Depends(...)` from `shared/antiabuse.py` to that route.
- **Error contract:** body-cap → 413, rate-limit → 429 with `Retry-After`, ALTCHA → 400 (`code="altcha_failed"`); all via `shared/errors` problem+json. Structural payload garbage is rejected earlier at 422 via `AltchaSolutionStr`/`validate_solution_format` in the request schema — **independent** of whether ALTCHA is enabled (keeps email-enumeration responses constant).
- **Two ALTCHA dependencies:** `verify_altcha` always checks; `verify_altcha_unless_authenticated` skips for a logged-in `Principal` (a session is already a trust anchor; captcha is only for anonymous submission).
- **ALTCHA off (no secret)** ⇒ `get_altcha_verifier` returns `NullAltchaVerifier` (pass-through) and the challenge route 404s.
- **Fail-open vs fail-closed asymmetry (deliberate):** the **rate limiter** fails open on Redis outage (availability > throttling); the **replay guard** fails closed-ish to a per-worker in-memory guard (a solved PoW must not be replayable for its whole TTL).
- **No `eval`** anywhere — pure HMAC/hash; no Redis Lua `EVAL` (atomic-enough via pipeline). Hash/HMAC compares use `hmac.compare_digest`.
- **Client IP** comes from `request.client.host` (uvicorn `--proxy-headers` behind the trusted edge nginx); do **not** parse `X-Forwarded-For` yourself. The body-cap is defense-in-depth only — the real size limit is nginx `client_max_body_size` (chunked requests carry no `Content-Length`).
- **Providers are lazily cached on `app.state`** (`_antiabuse_redis`, `_rate_limiter`, `_altcha_verifier`) and built from injected `Settings`; in tests replace them via `dependency_overrides` (or the `InMemory*`/`Null*` implementations).

**Related:** be-auth, be-applications, be-files, conventions
