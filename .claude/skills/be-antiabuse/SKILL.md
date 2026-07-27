---
name: be-antiabuse
description: ALTCHA proof-of-work captcha + sliding-window rate-limiting + body-cap for public/unauthenticated endpoints (magic-link, applications, attachments). Real nouns: GET /api/altcha/challenge, require_altcha, AltchaVerifier, RedisReplayGuard, RedisRateLimiter, body_cap, rate_limit_magic_link, ALTCHA_HMAC_SECRET. Use when working on captcha, rate limits, abuse protection, or public-endpoint hardening in backend/app/modules/antiabuse and backend/app/shared/{altcha,antiabuse,ratelimit}.py.
---

# Anti-Abuse (ALTCHA + rate-limit) — `backend/app/modules/antiabuse`

**Does:** Protects public/unauthenticated endpoints with a self-hosted ALTCHA proof-of-work captcha (no third-party, GDPR-clean), per-IP/mail/identity sliding-window rate-limiting, and a defensive request-body size cap. The module itself only exposes the challenge-issuing route. The enforcement logic lives in `app.shared`.

**Key files:**
- `modules/antiabuse/router.py` — the only router: `GET /altcha/challenge` (mounted under `/api`). The route returns 404 when ALTCHA has no configuration.
- `modules/antiabuse/__init__.py` — package docstring only.
- `shared/altcha.py` — pure ALTCHA crypto: `create_challenge`, `verify_solution`, `parse_solution`/`validate_solution_format`/`AltchaSolutionStr` (422 form-validator), `solve_challenge` (reference solver, tests only), `AltchaVerifier`, `NullAltchaVerifier`, `ReplayGuard`/`InMemoryReplayGuard`/`RedisReplayGuard`, `AltchaError`.
- `shared/antiabuse.py` — FastAPI-dependency wiring: `require_altcha`/`verify_altcha`, `require_altcha_unless_authenticated`, `body_cap` factory (+ `enforce_auth_payload_limit`, `enforce_application_payload_limit`), `rate_limit_magic_link[_verify]`, `rate_limit_applications`, `rate_limit_attachments`, provider getters (`get_rate_limiter`, `get_altcha_verifier`), `client_ip`, `SettingsDep`.
- `shared/ratelimit.py` — `RateLimiter` protocol + `Null`/`InMemory`/`RedisRateLimiter` (ZSET sliding window), `RateLimitResult`.

**Domain / data model:** No DB tables. All state lives in Redis with short TTLs.
- **Challenge** (dataclass): `algorithm` (`"SHA-256"`), `challenge` (`SHA-256(salt+number)` hex), `salt` (random + `?expires=<unix>` query encoded in), `signature` (`HMAC-SHA256(secret, challenge)`), `maxnumber`. The FE brute-forces `number` and returns a base64-JSON **Solution** in the `altcha` body field.
- **Verification** (`verify_solution`, pure, constant-time): checks the algorithm, the expiry (from the salt), the hash recompute, and the HMAC signature. It returns the signature as the **replay key**.
- **Replay guard:** Redis `SET NX EX` keyed `altcha:seen:<sig>`. On a Redis failure it does **not** fail open. It falls back to a per-worker `InMemoryReplayGuard`.
- **Rate-limit:** Redis ZSET (`rl:<key>`), score=timestamp, sliding window. Keys: `magic-link:ip:<ip>`, `magic-link:mail:<email>`, `magic-link-verify:ip:<ip>`, `applications:ip:<ip>`, `attachments:{principal|applicant|ip}:<id>`. It returns `RateLimitResult{allowed, retry_after}`.
- **Config knobs** (`app/settings.py`). ALTCHA: `altcha_hmac_secret` (None ⇒ ALTCHA off, `altcha_enabled` derived), `altcha_max_number` (100k), `altcha_challenge_ttl_seconds` (300, doubles as replay TTL). Rate limit: `rate_limit_enabled` (True), `rl_magic_link_ip_per_hour` (5), `rl_magic_link_mail_per_hour` (3), `rl_magic_link_verify_ip_per_hour` (20), `rl_applications_ip_per_hour` (10), `rl_attachments_per_hour` (30), `rl_default_write_per_hour` (100). Body caps: `max_auth_payload_bytes` (8192), `max_application_payload_bytes` (65536). Redis: `redis_url`.

**API surface:**
- `GET /api/altcha/challenge` — issue a fresh HMAC-signed PoW challenge (`AltchaChallengeOut`). It returns 404 (`NotFoundError`) when no `ALTCHA_HMAC_SECRET` is set. The routes of *other* modules (auth, applications, attachments) consume the remaining dependencies through `Depends`.

**Conventions & gotchas:**
- **Enforcement uses FastAPI dependencies, not middleware.** Throttling and captcha are therefore per-route and configurable, and they appear in the OpenAPI contract. To protect a new public POST, add the relevant `Depends(...)` from `shared/antiabuse.py` to that route.
- **Error contract:** body-cap → 413, rate-limit → 429 with `Retry-After`, ALTCHA → 400 (`code="altcha_failed"`). All of them go through `shared/errors` problem+json. The request schema rejects structural payload garbage earlier at 422 with `AltchaSolutionStr`/`validate_solution_format`. That check runs **independent** of whether ALTCHA is enabled, which keeps email-enumeration responses constant.
- **Two ALTCHA dependencies.** `verify_altcha` always checks. `verify_altcha_unless_authenticated` skips the check for a logged-in `Principal`. A session is already a trust anchor, so the captcha guards anonymous submission only.
- **ALTCHA off (no secret)** ⇒ `get_altcha_verifier` returns `NullAltchaVerifier` (pass-through) and the challenge route 404s.
- **Fail-open vs fail-closed asymmetry (deliberate).** The **rate limiter** fails open on a Redis outage, because availability beats throttling. The **replay guard** does not fail open. It falls back to a per-worker in-memory guard, because a solved PoW must not stay replayable for its whole TTL.
- **No `eval`** anywhere. The code uses pure HMAC and hash primitives. There is no Redis Lua `EVAL`, because a pipeline is atomic enough. Hash and HMAC compares use `hmac.compare_digest`.
- **Client IP** comes from `request.client.host` (uvicorn `--proxy-headers` behind the trusted edge nginx). Do **not** parse `X-Forwarded-For` yourself. The body-cap is defense in depth only. The real size limit is the nginx `client_max_body_size`, because chunked requests carry no `Content-Length`.
- **The app caches providers lazily on `app.state`** (`_antiabuse_redis`, `_rate_limiter`, `_altcha_verifier`) and builds them from the injected `Settings`. In tests, replace them through `dependency_overrides` or with the `InMemory*`/`Null*` implementations.

**Related:** be-auth, be-applications, be-files, conventions
