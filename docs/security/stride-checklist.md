# Pen-Test- / STRIDE-Checkliste (T-41)

Abnahme-Checkliste der Security-Härtung. Mapping STRIDE → Maßnahme (security.md §11)
→ Fundstelle im Code/Deploy → Status. `[x]` = umgesetzt + getestet.

## Spoofing (Identität)
- [x] Magic-Link: HMAC-signierter Token, Scope-gebunden, kein `?t=`-Query
      (`app/deps.py::_bearer_token`, `app/modules/auth/sessions.py`).
- [x] OIDC/PKCE + State/Nonce (`app/modules/auth/oidc.py`).
- [x] Echte Client-IP nur von vertrauenswürdigem Proxy; X-Forwarded-For wird im
      App-Code **nicht** geparst (`app/shared/antiabuse.py::client_ip`,
      `tests/test_hardening.py::test_client_ip_ignores_x_forwarded_for`).
- [x] `FORWARDED_ALLOW_IPS="*"` in `production` verboten (`app/settings.py`).

## Tampering (Integrität)
- [x] Serverseitige Validierung/Guards (`app/shared/guards.py`, forms/flow).
- [x] Webhook-HMAC `X-Signature` + `X-Timestamp` (`app/modules/webhooks/signing.py`).
- [x] Audit-Hash-Kette + Append-only-Trigger (`migrations/0006_audit_append_only.py`).
- [x] CSRF Double-Submit für cookie-authentifizierte Schreib-Requests
      (`app/middleware.py::CsrfMiddleware`, `tests/test_hardening.py`).

## Repudiation (Nachweisbarkeit)
- [x] Audit-Kette über Login/Statuswechsel/Stimme/Config/Export/Webhook-Config
      (`app/modules/audit/`), `verify_chain()` erkennt Lücken/Manipulation.

## Information Disclosure
- [x] PII-Trennung (`applicant`/`is_pii`), keine PII in Audit/URL/Log
      (security.md §9; Logs strukturiert ohne Secrets, `app/logging_config.py`).
- [x] Signierte, kurzlebige MinIO-URLs statt Direktzugriff (`app/modules/files/`).
- [x] Keine Stacktraces/Pfade nach außen (problem+json, `app/shared/errors.py`).
- [x] Security-Header inkl. strikter CSP an der JSON-API + `web`-nginx
      (`app/middleware.py`, `deploy/web/nginx.conf`).

## Denial of Service
- [x] Altcha-PoW auf `POST /auth/magic-link` + `POST /applications`
      (`app/shared/antiabuse.py::require_altcha`).
- [x] Rate-Limits (Redis, sliding window) auf sensiblen Endpunkten **und** ein
      Default-Limit auf allen schreibenden Endpunkten (api.md §7,
      `app/shared/antiabuse.py::rate_limit_default_write`) → 429 + `Retry-After`.
- [x] Body-Caps: Edge-`client_max_body_size` (primär) + App-Body-Cap (413).
- [x] Upload-Cap 10 MB + MIME-Sniffing (`app/modules/files/`).

## Elevation of Privilege
- [x] RBAC serverseitig (`app/deps.py::require_principal/require_group`).
- [x] Least-Privilege-DB: getrennte Service-User (`app`/`migrator`), Runtime-User
      ohne UPDATE/DELETE/TRUNCATE auf `audit_entry` (`deploy/db/roles.sql`,
      `tests/test_db_grants.py`).

## Edge / Proxy / SSRF
- [x] `api` ohne Host-Ports, nur über `web`-nginx erreichbar (`deploy/docker-compose.yml`).
- [x] X-Forwarded-Trust eng (`FORWARDED_ALLOW_IPS`, uvicorn `--proxy-headers`).
- [x] Webhook-SSRF-Guard: private/loopback/link-local/metadata blockiert, keine
      Redirects (`app/modules/webhooks/ssrf.py`, `tests/test_webhooks_ssrf.py`).

## CI / Supply-Chain
- [x] Dependency-Scan (`pip-audit`) als CI-Gate (`.github/workflows/ci.yml::be-deps-audit`).
- [x] Secrets nie im Repo: `.env` nicht eingecheckt, Mindestlänge erzwungen
      (`app/settings.py`), nur `.env.example` ohne Werte.
- [x] kein `eval`/`exec` in Evaluatoren (`tests/test_no_eval.py`).
