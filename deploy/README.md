# deploy

Compose stack for one VM. Internal traffic is plain HTTP. The external Nginx Proxy Manager
terminates TLS. `web` publishes `127.0.0.1:8080`. `postgres` also publishes a loopback-only
port for the admin CLI (see the service table). Every other service stays on the internal
network, so the internet cannot reach it.

## Start

```bash
git submodule update --init --recursive   # frontend/vendor/ui-kit (@stupa-makers/ui-kit)
cp .env.example .env        # fill in the values, NEVER commit
docker compose config -q    # validate the topology
docker compose up -d --build
```

> The frontend (`web`) takes the UI kit from the git submodule `frontend/vendor/ui-kit`.
> Check out the submodule before every `--build`. If you do not, `npm run build` fails on
> an unresolved `@stupa-makers/ui-kit` path. `deploy/deploy.sh` does this for you and syncs
> the submodule after `git pull`.

## Services

| Service | Role | Host port |
|---|---|---|
| `web` | nginx, serves the built SPA, routes `/api` to `api` | `127.0.0.1:8080` |
| `migrate` | one-shot: `alembic upgrade head`, then exit | — |
| `api` | FastAPI (uvicorn `--proxy-headers`) | — |
| `worker` | arq (mail send, nightly budget rollup) | — |
| `postgres` | PostgreSQL 16 | `127.0.0.1:5433` (admin CLI) |
| `redis` | Redis 7 (arq broker, rate limit, ALTCHA replay) | — |
| `minio` | S3 object store (attachments) | — |
| `clamav` | virus scan (the first start is slow because it loads the signatures) | — |
| `pytex` | internal Markdown→PDF renderer | — |
| `altcha` | ALTCHA Sentinel (captcha verifier) | — |
| `backup` | daily encrypted backup (pg_dump + MinIO mirror, age). Profile `prod`/`backup` | — |

Docker builds `web` from the repository root `..` in two stages (`web/Dockerfile`). Stage 1
builds the Angular frontend with Node. Stage 2 serves it with nginx. The image contains
`web/nginx.conf`, but compose also mounts it. You can therefore edit the file in production
without a rebuild, for example the `real_ip` CIDR of the Proxy Manager.

## Migrations

`migrate` runs once before `api` and `worker`. Both declare
`depends_on: migrate: service_completed_successfully`. `alembic upgrade head` is idempotent
and skips the revisions that already ran. You need no manual migration step, not even for an
update. `docker compose up -d --build` pulls the new image, and `migrate` applies the open
revisions before the application starts.

`migrate` can also run as its own database user (`DB_MIGRATION_URL`), separate from the
runtime user of the application.

### Least-privilege database roles (security.md §4/§10) — MANUAL production step

> ⚠️ **Not automatic.** Compose runs only `alembic upgrade head` (DDL/DML). It creates
> **no** roles and revokes **no** grants. Without this step the platform works, but
> **without** role separation. The runtime user could then change the audit log with UPDATE
> or DELETE. The append-only trigger from migration 0006 blocks that for every role, but the
> least-privilege layer is missing. This step is therefore mandatory in production.

`db/roles.sql` creates the separate service users (`app` for runtime, `migrator` for DDL,
optional `audit_writer`). It also revokes UPDATE, DELETE and TRUNCATE on `audit_entry` from
the runtime user. Run it **once as database superuser**. Run steps 1 to 4 **before**
`alembic upgrade head` and step 5 **after** it. The script is idempotent, so more runs do no
harm.

```bash
# 1) create the roles (before the migrations)
psql -U postgres -d antrag -f db/roles.sql
# 2) set the passwords from the secret store
psql -U postgres -d antrag -c "ALTER ROLE app PASSWORD '…'; ALTER ROLE migrator PASSWORD '…';"
# 3) run the migrations as migrator (DB_MIGRATION_URL) with compose-migrate
#    or manually: alembic upgrade head
# 4) revoke the audit grants again (step 5 in roles.sql, audit_entry now exists)
psql -U postgres -d antrag -f db/roles.sql
```

Then point `DATABASE_URL` to user `app` and `DB_MIGRATION_URL` to user `migrator` in `.env`.

## Networks

- `internal` — bridge with no published ports, so there is no ingress. Egress stays open.
  The worker needs SMTP, WebDAV and webhooks, pytex needs the tectonic bundle, and the api
  needs OIDC.
- `proxy` — in production this is the network of the Nginx Proxy Manager. Set `external: true`
  there and reference the NPM network.

## Configuration

All secrets live in `.env`. The template is `.env.example`. The API needs `DATABASE_URL`,
`SESSION_SECRET` and `MAGIC_LINK_SECRET` to start. OIDC, SMTP and ALTCHA turn on as soon as
you set their values. If the values are missing, the platform keeps the matching features off
and does not crash. For the full reference see the
[Configuration wiki](https://github.com/frederikbeimgraben/antragsplattform/wiki/Configuration).

### Bootstrap of the first admins (#70) — mandatory step with real OIDC auth

Under real OIDC auth (no mock) a fresh schema has **no** admin. Nobody holds `admin.*`, so
nobody can grant a role in the role and permission UI (`/admin/users`). To keep the platform
from locking itself out, the bootstrap grants the `admin` role to the first admins. It matches
them by OIDC subject **or** email. It is idempotent. It runs **at login** (the OIDC callback)
and **at startup**:

```dotenv
# comma-separated. Set at least one of the two.
BOOTSTRAP_ADMIN_SUBJECTS=f47ac10b-58cc-4372-a567-0e02b2c3d479,kc|alice
BOOTSTRAP_ADMIN_EMAILS=admin@hochschule.example,vorstand@stupa.example
```

- **Subject** = the OIDC `sub` claim from Keycloak. It is stable and hard to forge.
  **Prefer it.**
- **Email** = the `email` claim, matched case-insensitively. It applies **only when the
  id_token carries `email_verified: true`**. Without that check, an attacker could abuse an
  IdP or realm that allows self-registration without mail verification. The attacker could
  mint a token whose `email` is a bootstrap address and become admin. The platform therefore
  reads the email bootstrap **at login**, where the claim is fresh and verified. The
  **startup sweep matches by `sub` alone**, because the stored `principal.email` carries no
  verification flag. In practice an admin bootstrapped by email gets the role at the
  **next login**.
- The assignment is global (no Gremium scope), has no end date, sets `granted_by=bootstrap`
  and is **idempotent**. The bootstrap never grants the same role twice.
- After the first successful admin login the entry can stay and does nothing. Other admins
  can also replace it through the normal RBAC UI.

## Profiles

- **prod** — behind NPM, with external Keycloak, SMTP and Nextcloud, ClamAV on. It also starts
  the `backup` service:
  ```bash
  docker compose --profile prod up -d --build
  ```
  For the real NPM network, switch `proxy:` in the compose file to `external: true`.
- Default (no profile) = smoke and dev stack without `backup`.

## Backup and restore

For the daily encrypted backup (PostgreSQL and MinIO, age) and the tested restore procedure
see [`backup/README.md`](backup/README.md). The restore test is `../scripts/restore-smoke.sh`.

## Smoke test

```bash
../scripts/smoke.sh        # up + wait until healthy
../scripts/smoke.sh down   # remove the stack and its volumes
```

### Real stack smoke (core flows over HTTP and WS)

The script starts the full stack with the mock off and a bootstrap admin set. It then checks
the core flows over HTTP and WS alone:

- the API is up and `/api/health` answers
- the public branding read works
- the auth path answers 307 and `/auth/me` answers 401
- the WS handshake works

It uses its own `COMPOSE_PROJECT_NAME` and touches no other stack. It saves an existing
`deploy/.env` and puts it back afterwards. It cleans up completely.

```bash
../scripts/smoke-real-stack.sh        # up -> check the core flows -> teardown
```

The compose mapping fixes the host port at `127.0.0.1:8080`. `SMOKE_TIMEOUT` controls the wait
time and defaults to 600 seconds, because ClamAV loads for a long time.

CI runs the job `real-stack-smoke`. It is opt-in like e2e, so a default PR stays green and
skips it. Trigger it with `workflow_dispatch`, the PR label `run-real-stack-smoke`, or the
repository variable `RUN_REAL_STACK_SMOKE=true`. The job runs no frontend Selenium. The visual
harness covers that.
