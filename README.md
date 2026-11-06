# STUPA-Workflow

Web platform for the application, meeting and budget work of a student Gremium
(STUPA/AStA). Applicants submit through a public form. Gremium members process
applications, run meetings with live votes and a protocol, and manage cost center
budgets and invoices. The platform versions and audits all of it.

Monorepo, one VM, `docker compose`. Internally everything speaks plain HTTP. An
**external Caddy reverse proxy** in front of the stack terminates TLS. The stack does not
handle certificates and does not contain a built-in identity provider.

Full documentation in the [Wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki).

## Stack

- **Backend** — Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
  arq worker. uvicorn runs with `--proxy-headers` in a non-root container.
- **Frontend** — Angular (strict TS, standalone components, separate `.html`/`.scss`),
  @ngx-formly, RxJS, signals.
- **Data** — PostgreSQL 16 (config and submissions as versioned JSONB), Redis 7 (arq
  broker, rate limit, ALTCHA replay), MinIO (S3 attachments and receipts), ClamAV.
- **PDF** — `typst`, an internal Markdown→PDF render service (Typst, HSRT design), isolated from egress.
- **Captcha** — ALTCHA Sentinel (self-hosted, proof of work).

## Features

The backend works and has tests (about 5900 test functions in unit and integration suites).
It implements:

- **Auth & RBAC** — OIDC against any IdP with a discovery document, such as authentik or
  Keycloak (authorization code + PKCE, server session), and a magic link for applicants
  (HMAC-hashed token, valid until a newer link, the archive or the anonymization ends it). Global roles and permissions come from OIDC groups. Meeting,
  protocol and vote rights are Gremium permissions of a Gremium role. Each `/admin/` page has its own
  permission. An admin can merge an old account into a new one (`admin.users.merge`).
- **Forms** — forms as versioned JSON. The backend validates the definition and the
  answers against a schema. This covers `visibleIf` and compute through JsonLogic, with
  ReDoS-hardened patterns.
- **Applications** — create an application (public, with captcha, rate limit and payload
  cap), edit it with a version diff, timeline, comments and GDPR anonymization. A guest
  confirms the e-mail address within a configurable window. The wizard uploads attachments
  as drafts before the submit. A holder of `application.create_on_behalf` captures an
  application for an applicant (an account or a guest).
- **Flow** — a declarative state machine with a guard evaluator (whitelist operators in
  a dispatch table, **no `eval`**) and transition actions
  (`notify`, `webhook`, `addToNextSession`, `assignBudget`, `assignBudgetFromField`).
- **Voting** — quorum (count or percent), majorities (simple, absolute, two thirds),
  a tie rejects a motion, a lot decides an election tie, secret ballot (the choice stays separate from the identity). The platform
  scopes read access to the Gremium.
- **Meetings / LiveVote** — meetings with an agenda, attendance and a live vote over
  WebSocket (voter channel plus read-only beamer stream). The protocol starts with the
  meeting. The minute-taker can hand over during a live meeting. A meeting of a Gremium
  without a quorum can allow public participation: guests join with a QR code (`/j/:code`),
  the meeting lead admits them, and they watch or vote. Each person gets an ICS calendar feed.
- **Protocol** — meeting protocol (Markdown), votes as snippets, an async PDF render
  (typst → MinIO) and a mail dispatch when you finalize it.
- **Delegations** — meeting-bound vote and representation delegations plus a per-Gremium
  substitute pool. During a live meeting the meeting lead can enter a substitute from the pool
  for a missing member.
- **Budget** — a hierarchical cost center tree with fiscal years, top-down allocation,
  bookings and transfers, and **invoices with ZUGFeRD/Factur-X import**. The
  platform audits every money mutation.
- **Notifications** — mail templates (Jinja2, sandboxed, DE/EN), rules
  (event→template→recipient), per-user preferences, dispatch through the arq worker.
- **Audit** — an append-only hash chain (`sha256(prev || canonical)`), a DB trigger
  against UPDATE and DELETE, and chain verification (nightly and on demand, the result is stored).
- **Webhooks** — outgoing event webhooks with an SSRF guard (blocks private, loopback,
  link-local and NAT64 targets, pins DNS against rebinding) and an HMAC signature.
- **Backups** — age-encrypted whole-platform backups inside the app (`/admin/backups`), a
  nightly job, retention and an in-app restore.
- **Privacy** — GDPR erasure requests, anonymization, subject-access export and retention.
- **MCP** — an MCP server (`mcp/`) lets an agent act through the API as the logged-in user.

Frontend: a start page with a work list, list/detail pages for applications, tasks, votes,
meetings (list or calendar), bookings and invoices, the budget overview, the account area and
the admin configuration (forms, flow, Gremien, roles, branding, …).

Open work and roadmap: a wider E2E suite (Playwright) and more flow action handlers.

## Setup (local)

You need Docker and Docker Compose v2.

```bash
cd deploy
cp .env.example .env        # fill in the values. See Wiki/Configuration
docker compose up -d --build
```

Migrations run on their own. A one-shot `migrate` service applies `alembic upgrade
head` before `api` and `worker` start. The SPA then answers at
<http://127.0.0.1:8080/> (`WEB_PORT` moves it). Postgres also exposes `127.0.0.1:5433`, for the admin CLI
only. Liveness: `/healthz` (web) and `/api/health` (api).

> On the first start, ClamAV downloads signatures for several minutes (long
> `start_period`).

## Repo layout

```
backend/    FastAPI app, arq worker, modules, migrations, tests
frontend/   Angular SPA + design system
typst/      Markdown→PDF render service (FastAPI + Typst)
mcp/        MCP server (agent/API access)
admin-cli/  terminal admin tool that works on the database directly
deploy/     docker-compose.yml, web/ (nginx + multi-stage build), .env.example
scripts/    helper scripts (smoke, e2e, restore smoke, admin CLI, role maintenance)
```

## Development

Backend:

```bash
cd backend
pip install -e '.[dev]'
ruff check . && basedpyright && pytest
```

Frontend:

```bash
cd frontend
npm ci
npm run lint && npm run typecheck && npm test && npm run build
```

TDD is mandatory. Every PR must pass the CI gate green. The rules are in
`.claude/skills/conventions/SKILL.md`. Never push to `main` directly. Keep
secrets in `deploy/.env` only, which `.gitignore` blocks. Never commit a secret.

## Branching and releases

The specs hold the rules for branches, pull requests, releases and migrations. This
section only links to them:

- [S/shared/git/000224](specs/style/shared/git/000224_target-development.md): An app pull request targets development
- [S/shared/git/000423](specs/style/shared/git/000423_one-pr-per-package.md): One branch and one pull request per package
- [S/shared/git/000424](specs/style/shared/git/000424_sync-main.md): Sync main into development first
- [S/shared/git/000054](specs/style/shared/git/000054_merge-go.md): A merge needs the go of the owner
- [S/shared/git/000052](specs/style/shared/git/000052_no-auto-merge.md): A pull request is never set to auto-merge
- [S/shared/git/000056](specs/style/shared/git/000056_ui-kit-flow.md): ui-kit changes go to ui-kit development first
- [S/shared/git/000436](specs/style/shared/git/000436_release-flow.md): A release goes from development to main by pull request
- [S/shared/git/000053](specs/style/shared/git/000053_release-tags.md): Only the owner tags a release
- [S/shared/git/000057](specs/style/shared/git/000057_release-notes.md): Release notes list migrations and steps
- [S/shared/git/000434](specs/style/shared/git/000434_environments.md): Dev follows development, production follows tags
- [S/shared/git/000390](specs/style/shared/git/000390_typst-pin.md): The typst version is pinned in two places
- [S/backend/database/000068](specs/style/backend/database/000068_hash-revision.md): A migration has a hash ID
- [S/backend/database/000069](specs/style/backend/database/000069_one-head.md): Alembic has one head
- [S/backend/database/000071](specs/style/backend/database/000071_data-revision.md): A data change has its own revision

## Security (short)

Sessions are signed HttpOnly cookies (`itsdangerous`). OIDC runs with PKCE plus state
and nonce. The platform stores a magic-link token only as an HMAC hash. Public endpoints
sit behind ALTCHA and a Redis rate limit. Outgoing webhooks sit behind an SSRF guard.
The audit log is append-only at the database level. RFC 9457
`application/problem+json` is the error contract. More in the
[Security wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki/Security).
