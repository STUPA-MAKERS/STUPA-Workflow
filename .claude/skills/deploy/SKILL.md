---
name: deploy
description: Single-VM docker-compose stack (web/migrate/api/worker/postgres/redis/minio/clamav/pytex/altcha/backup) behind an external Nginx Proxy Manager, with nginx routing, alembic one-shot migrate, age-encrypted backup/restore, least-privilege DB roles, and .env config. Use when working on the compose topology, nginx reverse-proxy/CSP, deploy/update scripts, DB roles, or backup/restore in deploy/.
---

# Deploy stack (one VM, docker-compose) — `deploy`

**Does:** Defines the whole production stack as docker-compose for a single VM: SPA+nginx edge, FastAPI api, arq worker, one-shot alembic migrate, Postgres/Redis/MinIO/ClamAV/pytex/altcha, and a daily encrypted backup. TLS is terminated by an external Nginx Proxy Manager; only `web` is host-bound on `127.0.0.1:8080`, everything else is internal-only (no Internet ingress).

**Key files:**
- `docker-compose.yml` — the full stack: 11 services, networks (`internal`, `pytex_net` egress-less, `proxy`), volumes, healthchecks, `prod`/`backup` profiles.
- `docker-compose.e2e.yml` — overlay for Playwright e2e: adds `mailpit` (SMTP sink), `seed` one-shot (`profiles:[seed]`), `:ro,z` SELinux relabel + IPv4 healthcheck for `web`. Mock OIDC stays OFF.
- `docker-compose.keycloak.yml` — local-only OIDC: Keycloak `start-dev --import-realm`, `host.docker.internal` wiring. Not for prod.
- `web/Dockerfile` — multi-stage: node:22 builds the Angular SPA (`dist/antragsplattform/browser`), nginx:1.27 serves it. Build context = repo root.
- `web/nginx.conf` — plain-HTTP server: `real_ip` from proxy, `/api/` proxy with body caps, WS upgrade, `.well-known/oauth-*` + dynamic `/manifest.webmanifest` proxies, SPA fallback, security headers (CSP, X-Frame-Options DENY).
- `db/roles.sql` — least-privilege DB roles (`migrator`/`app`/`audit_writer`); revokes UPDATE/DELETE/TRUNCATE on `audit_entry` from runtime user. Run as superuser, two-stage around `alembic upgrade head`.
- `deploy.sh` — prod update: `git pull --ff-only` → build all → recreate only services whose image-id changed (`--profile prod`).
- `.env.example` — full secrets/config template (DB, Redis, MinIO, OIDC, SMTP, Nextcloud, webhooks, altcha, pytex, rate-limits, CSRF, backup). Copy to `.env`.
- `backup/backup.sh` — `pg_dump` (custom) + `mc mirror` MinIO → one age-encrypted `antrag-<UTC>.tar.age`; retention prune; optional off-host rsync.
- `backup/restore.sh` — destructive restore: `age -d` → `pg_restore --clean --if-exists` + `mc mirror --remove`. Confirms `RESTORE` unless `FORCE=1`.
- `backup/entrypoint.sh` — writes crontab from `BACKUP_CRON`, runs busybox `crond`; with args runs one-shot instead.
- `backup/lib.sh` — shared `need`/`pg_env`/`mc_env`/`age_recipient`/`log` helpers (derive libpq env from `POSTGRES_*`, NOT `DATABASE_URL`).
- `backup/Dockerfile` — postgres:16-alpine + pinned `mc` + `age` + `rsync`.
- `README.md`, `backup/README.md` — operator runbooks (start, migrations, roles, profiles, backup/restore).
- `e2e/seed.py`, `keycloak/antrag-realm.json` — e2e seeding + Keycloak realm import.

**Domain / data model:** Not an app domain module — it's infra. The "model" is the service topology:
- **Services:** `web` (nginx SPA + `/api` proxy, only host port `127.0.0.1:8080:80`), `migrate` (one-shot `alembic upgrade head`, `restart:no`), `api` (uvicorn `--proxy-headers`, no host port), `worker` (`arq worker.main.WorkerSettings`), `postgres:16-alpine`, `redis:7-alpine` (appendonly), `minio` (S3, console :9001), `clamav` (long ~5min signature load → 300s start_period), `pytex` (md→pdf renderer, pytex v1.0.0), `altcha` (ALTCHA Sentinel captcha, internal :8080), `backup` (`prod`/`backup` profiles only).
- **Networks:** `internal` (bridge, no published ports → no ingress, egress allowed for SMTP/WebDAV/Webhooks/OIDC), `pytex_net` (`internal:true` → NO egress; api/worker↔pytex render path, closes any compile-time exfil channel), `proxy` (in prod set `external:true` to reference the NPM-managed network).
- **Volumes:** `pg_data`, `redis_data`, `minio_data`, `clamav_data`, `pytex_cache`, `backups`, `altcha_data`.
- **Startup ordering:** `migrate` waits on `postgres` healthy; `api`/`worker` wait on `migrate` `service_completed_successfully` + datastores healthy; `web` waits on `api` healthy; `worker` only waits `clamav` *started* (scan task retries until clamd ready).
- **DB roles:** `migrator` (DDL, `DB_MIGRATION_URL`), `app` (DML runtime, `DATABASE_URL`), optional `audit_writer` (INSERT/SELECT only). Migration 0006 sets the append-only trigger + conditional audit grant.

**API surface:** No router here. nginx routes (`web/nginx.conf`): `GET /healthz` (container liveness, returns `ok`); `/api/` → `api:8000` (body cap 1m); `/api/applications/{id}/attachments` and `/api/invoices/(parse|file)` → larger 11m body cap; `/api/ws/` → WS upgrade (3600s read timeout); `/.well-known/oauth-(authorization-server|protected-resource)` → api (MCP OAuth discovery); `/manifest.webmanifest` → `api:8000/api/manifest.webmanifest` (dynamic PWA manifest); `/` → SPA fallback (`try_files … /index.html`).

**Conventions & gotchas:**
- **Only `web` is host-bound** (`127.0.0.1:8080`); never publish other service ports. External NPM proxies to it (set `proxy` net `external:true` in prod).
- **`ENVIRONMENT=production` is mandatory in prod** — it arms invoice-AV fail-closed + the X-Forwarded-* spoofing guard; `STRICT_SECURITY` (default on) keeps hardening even if forgotten. App default is `development`.
- **`FORWARDED_ALLOW_IPS` must be the concrete direct upstream IP** (the web/nginx container net), NEVER whole RFC1918 ranges — otherwise any internal host can spoof `X-Forwarded-For` (rate-limit bypass / wrong audit IP). `*` is forbidden in production.
- **`nginx.conf` is baked into the image AND bind-mounted** so prod edits (e.g. `set_real_ip_from` CIDR) need no rebuild. Edit the mounted file for the real proxy CIDR. CSP/security headers live here at the edge.
- **`db/roles.sql` is a MANUAL prod step** — compose only runs `alembic upgrade head`; it does NOT create roles or revoke grants. Without it the platform runs but with no role separation. Two-stage: steps 1–4 before, step 5 after migrations; idempotent.
- **`DB_MIGRATION_URL` is empty by default** — default Postgres has no `migrator` role, so a set value would fail `alembic upgrade head` on a fresh DB. env.py falls back to `DATABASE_URL` (Issue #38). See [[alembic-revision-id-limit]] (revision ids ≤32 chars or deploy breaks).
- **Bootstrap admins** (`BOOTSTRAP_ADMIN_SUBJECTS` / `BOOTSTRAP_ADMIN_EMAILS`): under real OIDC a fresh schema has no admin; subjects match at login + startup-sweep, emails only at login and only when `email_verified:true`.
- **`migrate` is idempotent** — `docker compose up -d --build` re-runs it on update; alembic skips applied revisions. No manual migration step.
- **Backup is encrypt-only on-host** — host knows only `BACKUP_AGE_RECIPIENT` (public key); private `age.key` lives off-host, supplied only at restore time via `/secrets/age.key` (gitignored, `:ro,z` mounted). Empty recipient ⇒ `backup` service refuses to start.
- **Backup uses `POSTGRES_*`/`MINIO_*` directly, NOT `DATABASE_URL`** — the latter carries the asyncpg driver that libpq tools can't parse.
- **Restore is destructive** (`pg_restore --clean`, `mc mirror --remove`); prompts for `RESTORE` unless `FORCE=1`. Stop `api worker` first.
- **`:z`/`:ro,z` mounts** are SELinux relabel for Fedora/rootless-podman hosts; no-op on CI/ubuntu. Missing `z` → "Permission denied" on the mounted file.
- **ClamAV start is slow** (signature download, several minutes) — hence the 300s start_period; don't treat early `unhealthy` as a failure. `SMOKE_TIMEOUT` default 600s.
- Smoke: `../scripts/smoke.sh`, real-stack smoke `../scripts/smoke-real-stack.sh`, restore-smoke `../scripts/restore-smoke.sh` (all opt-in CI jobs).

**Related:** be-admin, be-audit, be-files, conventions
