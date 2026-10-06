# STUPA-Workflow

Web platform for the application, meeting and budget work of a student Gremium
(StuPa/AStA). Applicants submit through a public form. Gremium members process
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

The backend works and has tests (about 4500 test functions in unit and integration suites).
It implements:

- **Auth & RBAC** — OIDC against any IdP with a discovery document, such as authentik or
  Keycloak (authorization code + PKCE, server session), and a magic link for applicants
  (HMAC-hashed single-use token). Global roles and permissions come from OIDC groups. Meeting,
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
  tie-break, secret ballot (the choice stays separate from the identity). The platform
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
deploy/     docker-compose.yml, web/ (nginx + multi-stage build), .env.example
scripts/    helper scripts (smoke, role maintenance)
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

TDD is mandatory. Every PR must pass the CI gate green. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the details. Never push to `main` directly. Keep
secrets in `deploy/.env` only, which `.gitignore` blocks. Never commit a secret.

## Branching and releases

A protected `main`, one integration branch `development` and tag-based delivery. Feature
PRs go to `development`. Each merge to `development` deploys the dev site. A release merges
`development` into `main` and tags it. There is no other long-lived branch.

| Branch | Purpose | Rules |
|---|---|---|
| `main` | always green, always deployable | **protected**: PR + green CI + 1 review, no direct push, linear history |
| `development` | integration branch, deploys the dev site on each merge | PR + green CI, no direct push |
| `feat/*`, `fix/*`, `chore/*`, `docs/*` | short-lived branches off `development` | merge by PR (squash) into `development`, delete after the merge |
| `hotfix/*` | urgent production fix off the running release tag | PR → `main`, then a new patch tag |

**Releases.** Production runs on a **tag**, not on the HEAD of `main`. Versions follow
SemVer: `vMAJOR.MINOR.PATCH`. You tag a release on `main`. CI then builds the images,
marks them with the tag and deploys them. This keeps the production state reproducible
at any time. A rollback is a re-deploy of the previous tag.

```
feat/x ──PR──▶ development ──PR──▶ main ──tag v1.2.0──▶ Build+Deploy
                                    ▲
hotfix/y ──PR───────────────────────┘  (from v1.2.0)  ──tag v1.2.1──▶ Deploy
```

**DB migrations** belong to the release. Prefer additive, backward-compatible Alembic
steps: first add the column, remove the old one later. A rollback of the app then does
not fail on the database. Revision ids are 32 characters or shorter.

Recommended branch protection for `main`: "Require a pull request before merging" (1
approval), "Require status checks to pass" (CI: ruff + basedpyright + pytest + ng build
+ jest), "Require linear history", "Require branches to be up to date".

## Security (short)

Sessions are signed HttpOnly cookies (`itsdangerous`). OIDC runs with PKCE plus state
and nonce. The platform stores a magic-link token only as an HMAC hash. Public endpoints
sit behind ALTCHA and a Redis rate limit. Outgoing webhooks sit behind an SSRF guard.
The audit log is append-only at the database level. RFC 9457
`application/problem+json` is the error contract. More in the
[Security wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki/Security).
