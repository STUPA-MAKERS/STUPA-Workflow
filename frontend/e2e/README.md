# E2E tests (T-40) — Playwright against the real compose stack

End-to-end coverage of the core user journeys (testing.md §3) against the **real**
stack (FastAPI + Angular + Postgres + Redis + MinIO + pytex behind Nginx), **not**
against the mock API (OFF since #101). Magic-link mails land in the `mailpit` SMTP
sink.

## Run

```bash
scripts/e2e.sh
```

The script starts the stack under its own `COMPOSE_PROJECT_NAME=antrag-e2e`, so it
leaves other stacks alone. It writes a throwaway `deploy/.env` (mock OFF, mailpit
SMTP, ALTCHA and rate limit OFF for determinism), seeds deterministic fixtures, runs
Playwright and cleans up fully (`down -v`). Precondition: run
`npm ci && npx playwright install --with-deps chromium` once in `frontend/`.

## Covered — gating (blocking, every PR, CI job `e2e`)

Deterministic. No Keycloak, pytex or ClamAV on the gate path:

- **01 apply** — the public apply wizard through ALL steps to the review summary
  (application type → contact → dynamic form of the seeded form version → review).
  The final submit click is NOT part of the assertion. The frontend ALTCHA component
  is a stub (`altcha-stub-solution`), and the backend schema rejects it with 422 as a
  malformed altcha solution. The UI submit is blocked independent of T-40 (issue
  #111, the real captcha wiring is a separate task). Test 02 covers the real
  application *creation* and the follow-up journey (scenario 1, part).
- **02 magic-link-flow** — create the application → magic link (real SMTP over
  mailpit) → edit → the admin moves it to `pruefung` with a flow transition →
  read-only and locked (scenarios 1 + 2 + read-only).
- **03 rbac** — an unauthenticated visitor does not see the guarded routes
  (scenario 7).
- **04 admin-form** — form builder: add a field → the form version **persists**
  (the success toast fires only on a 2xx from the server) (scenario 6).
- **05 budget-pots** — budget pots view plus pot creation.

**T-40 therefore covers 4 of the 7 SDS scenarios green and for real** (1 apply plus
magic link, 2 flow, 6 admin config, 7 RBAC) **plus** budget pots and read-only.

## Left out on purpose — tracked as follow-up issues, not as hollow stubs

Frederik's rule is "stable before flaky". A full green run of all 7 scenarios against
the real stack is not reliably deterministic in CI (WebSocket timing, pytex-tectonic,
Keycloak, ClamAV). These scenarios move to clearly named issues. Empty
`test.fixme()` stubs would only fake coverage.

| Scenario (SDS) | Issue |
|----------------|-------|
| 3 async voting | #107 |
| 4 live vote (WebSocket, 2 contexts + beamer) | #108 |
| 5 protocol → PDF → send (pytex) | #109 |
| OIDC login over a Keycloak test realm | #110 |

## Architecture notes

- **Seed** (`deploy/e2e/seed.py`, one-shot service `seed`): creates an **active form
  version and flow version** for the default application type `foerderantrag` that
  migration `0018` seeds. Without them `POST /applications` fails. The seed also mints
  an **admin server session** with the application's own `create_principal_session`,
  which knows `SESSION_SECRET`. That yields the `ap_session` cookie. This is no
  production backdoor: only the test seed calls the normal signing function, in the
  same way as `force_login` in Django. `global-setup.ts` builds the admin
  `storageState` from it.
- **CSRF**: the middleware enforces CSRF only when an auth cookie is present
  (middleware.py). The unauthenticated setup POSTs (apply, magic link) need no CSRF
  token. Authenticated writes go through the real Angular UI, whose interceptor
  mirrors the double-submit token.
- **OIDC and ALTCHA OFF**: the optional secrets must NOT be set to an empty string.
  `app.settings` demands `min_length=16`, so an empty value breaks `get_settings()`
  and migrate exits 1. `scripts/e2e.sh` strips the empty lines from the e2e `.env`.
- **Migration 0019** (`application.manage`): the flow transition endpoints and the
  frontend gating need the permission `application.manage`. Migration `0003` seeded it
  to NO role, the same seed gap as `form.configure` and `flow.configure` in 0010 and
  0016. Without it even an admin cannot move an application through the flow.
  `0019_seed_application_manage` adds it to the admin role, idempotent
  (down_revision = 0018, single head).
- **web healthcheck and mounts** (overlay): web uses `127.0.0.1` instead of
  `localhost`, because nginx listens on IPv4 only and the conf mount is read-only. The
  `:z` mounts serve SELinux and podman locally and are a no-op on CI docker.

## Defect found (separate bugfix task, not part of T-40)

The backend mail links to `/antrag/<id>#t=<token>` (a fragment, security.md §1: the
token never reaches the server). The frontend reads the token on `/status?t=…&app=…`
and has **no** `/antrag/:id` route. The magic-link landing is therefore broken end to
end. The gating test covers the magic-link *capability* over the `/status` path that
the frontend supports, with the token pulled from mailpit.
