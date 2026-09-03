# CLAUDE.md — agent guide to STUPA-Workflow

Entry point for any AI agent (Claude Code and other wrappers) that works in this repo. It maps the
codebase to a set of **skills** (per-module navigation docs) and **memories** (durable conventions,
specs, traps). Use them to orient fast instead of reading everything again.

## What this is

**STUPA-Workflow** (also called *antragsplattform*) — a web platform for the application, meeting,
and budget work of a student government (StuPa/AStA). Applicants submit through a public form.
Gremium members process applications, run meetings with live votes and a protocol, and manage
cost-center budgets and invoices. The platform versions and audits all of this work. Monorepo, one
VM, `docker compose`.

**Stack:** Backend = Python 3.13 / FastAPI / Pydantic v2 / SQLAlchemy 2.0 async + Alembic / arq
worker. Frontend = Angular 20 (strict TS, standalone, separate `.html`/`.scss`, signals,
ngx-formly). Postgres 16 (versioned JSONB), Redis, MinIO (S3), ClamAV, pytex (internal
Markdown→PDF), ALTCHA.

Full prose: `README.md`. Workflow & Definition of Done: `CONTRIBUTING.md`.

## How to navigate (read in this order)

1. **`.claude/skills/conventions/`** — house rules (problem+json, tz-aware, server-side RBAC, no
   `eval`, i18n parity, coverage gates, alembic policy). Read this before changing any code.
2. **The relevant `be-*` / component skill** — open the skill for the module you touch. Each
   skill's `description` says when to use it. The body maps key files, the domain model, the API
   surface, and the traps. Skills cross-link siblings (`be-x`) and memories (`[[slug]]`).
3. **The memory it links** — `.claude/memory/` holds specs, prior decisions, and status. Read a
   linked `[[memory]]` when it is relevant to your change.

## Skills (`.claude/skills/<name>/SKILL.md`)

Cross-cutting:
- **conventions** — house rules, Definition of Done, test/coverage gates, alembic migration policy,
  `app/shared/` utilities. **Start here.**

Backend domain modules (`backend/app/modules/<module>`):
- **be-auth** — OIDC+PKCE / magic-link, sessions, RBAC, OAuth2 tokens for MCP *(critical)*
- **be-admin** — branding, gremium roles, site-config draft/activate, per-page admin RBAC
- **be-applications** — application lifecycle, version diff, timeline, comments, anonymization
- **be-application-types** — bind a form version + flow to an application type
- **be-forms** — versioned form JSON, definition/answer validation, JsonLogic visibleIf/compute
- **be-flow** — declarative state machine, guard evaluator (no eval), transition actions
  *(critical)*
- **be-deadlines** — named deadline policies referenced by the flow
- **be-voting** — quorum/majority/secret ballot, tally, gremium-scoped reads *(critical)*
- **be-livevote** — meetings, agenda items, attendance, live vote over WebSocket + beamer stream
- **be-protocol** — meeting protocol (Markdown→PDF), vote snippets, finalize + mail
- **be-delegations** — meeting-bound vote delegations + substitute pool
- **be-budget** — cost-center tree, fiscal years, allocations, bookings/transfers, ZUGFeRD
  invoices *(critical)*
- **be-notifications** — mail templates (Jinja2 sandboxed), rules, prefs, arq dispatch
- **be-webhooks** — outgoing event webhooks, SSRF guard, HMAC signature *(critical)*
- **be-audit** — append-only sha256 hash chain, DB trigger, chain verification *(critical)*
- **be-backup** — whole-platform age-encrypted backups + in-app restore, `/admin/backups` *(critical)*
- **be-config-revision** — versioned config + audit + revert
- **be-files** — MinIO attachments, ClamAV scan, signed URLs
- **be-pdf** — client to the pytex render service (protocols only; applications no
  longer render a PDF)
- **be-privacy** — DSGVO/GDPR anonymization, export/erasure
- **be-calendar** — calendar/ICS feed for meetings
- **be-antiabuse** — ALTCHA captcha + rate-limiting + body-cap for public endpoints

Components:
- **frontend** — Angular 20 SPA (`frontend/`): core/shared/features/pages, design system, build
- **mcp** — MCP server (`mcp/`): act on the platform through its API as the logged-in user, PKCE
  browser grant
- **pytex** — internal Markdown→PDF render service (`pytex/`), trust levels, variants
- **deploy** — docker-compose production stack (`deploy/`), services, networking

## Memory (`.claude/memory/`)

Durable project knowledge: how-to-work preferences, UI/FE conventions, data shapes, feature specs,
and time-stamped backlogs. Index + per-file links: **`.claude/memory/MEMORY.md`**.

> This repo intentionally does **not** mirror internal security-audit findings. Do not add them.

## For other agent wrappers

- `AGENTS.md` is a symlink to this file.
- `.agents/skills` is a symlink to `.claude/skills`.

So a wrapper that looks for `AGENTS.md` or `.agents/skills` resolves to the same content.

## Quick command reference

- Backend (`backend/`): `ruff check .` · `basedpyright` · `pytest` · `pytest -m integration`
- Frontend (`frontend/`): `npm run lint` · `npm run typecheck` · `npm test` · `npm run build`
- Migrations (`backend/`): `alembic revision -m "..."` (hash id) · `alembic heads` (must be 1) ·
  `alembic upgrade head`
- Stack (`deploy/`): `docker compose config -q` · `docker compose up -d --build`

See `conventions` skill + `CONTRIBUTING.md` for the full gates.
