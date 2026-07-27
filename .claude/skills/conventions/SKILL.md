---
name: conventions
description: STUPA-Workflow house rules, Definition-of-Done, test/coverage gates, alembic migration policy, and the shared/ backend utilities (problem+json, guards, jsonlogic, RBAC). Read this FIRST before changing backend or frontend code, opening a PR, or writing a migration. Use when unsure how this repo expects code, errors, types, i18n, or DB migrations to be done.
---

# Project conventions — house rules & Definition of Done

The non-negotiables. Source of truth: `CONTRIBUTING.md`, `.github/pull_request_template.md`,
`backend/migrations/README.md`. Each rule encodes a bug that already cost the team once.

## Workflow

- **TDD: Red → Green → Refactor.** Write the failing test first, then minimal code, then clean up.
  No `skip`/`xfail` without a linked reason (issue).
- **Finish the job:** branch → commit → push → PR, then watch CI and fix failures. See
  `[[repo-ship-workflow]]`.
- **Ask before design decisions** (`[[ask-all-design-decisions]]`). Otherwise execute autonomously
  (`[[work-autonomously]]`). Track work with the todo tool (`[[always-track-todos]]`,
  `[[track-side-requests]]`).

## Backend Definition of Done

- **tz-aware everywhere** — `timestamptz` in DB, aware `datetime` in Python (`datetime.now(UTC)`, never
  `utcnow()`). A single naive value poisons every comparison (has crashed RBAC + caused WS 403s).
- **problem+json on ALL error paths** — every 4xx/5xx returns `application/problem+json` (RFC-9457),
  including new branches. `app/shared/errors.py` holds the implementation (`ProblemDetail`, the
  handlers and the OpenAPI rewrite). Never return a bare string or the default `detail` of FastAPI.
- **RBAC enforced server-side** — check the permission in the backend, not just in FE gating. Roles and
  owner come from the session, never the request body. Object-owner ≠ caller is the most common leak.
  See `[[admin-domain-rules]]`.
- **Strictly typed inputs** — Enums/`Literal` instead of free strings. Validate query/body/path via
  Pydantic/`Annotated`. No open `str` status fields. Python ≥3.13, fully annotated, no bare `Any`
  (`[[python-strong-typing]]`).
- **No `eval`** — flow/form guards run through a whitelist dispatch table (`app/shared/guards.py`,
  `app/shared/jsonlogic.py`), never `eval`.

## FE/BE contract

- **Identical field/header/cookie names** FE↔BE, **camelCase** in JSON. No FE-invented fields, no silent
  `snake_case`↔`camelCase` drift — both sides compile, then they fail silently at runtime.
- camelCase base model: `app/shared/config_schemas.py` (alias, `extra=forbid`).

## Frontend Definition of Done

- **i18n de/en parity** — every new string in BOTH locales, nothing hardcoded. Edit EN too
  (`[[admin-domain-rules]]`).
- **a11y** — labels/`aria-*`, focus order, keyboard, contrast.
- **Dark/Light** — verify in both themes. Check against the **prod** build (inlineCritical differs from
  dev).
- **Run `npm run build`** after CSS changes — bundle/style budgets fail the Docker build but pass jest+tsc
  (`[[ng-build-budgets]]`).
- UI conventions: `[[ui-patterns-and-backlog2]]`, `[[empty-state-convention]]`, `[[no-uuids-in-ui]]`,
  `[[loading-overlay-convention]]`, `[[tailwind-preflight-off-borders]]`, `[[mobile-view-decisions]]`.

## Tests & coverage gates (CI blocks on these)

- Backend ≥ **97 %** (lines + branches). Frontend: statements **98 %**, branches **96 %**, functions
  **98 %**, lines **99 %**.
- **100 % branch** for critical modules: `auth`, `voting`, `flow`, `budget`, `webhooks`, `audit`
  (`scripts/coverage_critical.py`).
- Local (BE): `ruff check .` + `basedpyright` (0 errors) + `pytest`. Local (FE): `npm run lint`,
  `npm run typecheck`, `npm test`. CI order: `Lint → Typecheck → BE-Unit → BE-Integration →
  Contract (Schemathesis) → FE-Unit → E2E (Playwright) → Coverage-Gate → Image-Build + Smoke`.

## Alembic migrations

- New revision = **hash id** (`cd backend && alembic revision -m "..."`), NOT the old `000N` prefix and
  **no `--rev-id`**. The `0001…0017` chain stays as-is. Only new revisions get hash ids.
- `alembic heads` MUST show exactly one head. `alembic upgrade head` MUST be green. Single-head is the
  one intended merge-conflict point.
- Revision ids MUST be ≤ 32 chars (`alembic_version varchar(32)`) — `[[alembic-revision-id-limit]]`.
- The `0002` migration creates tables and models via `Base.metadata.create_all` (single-source). Pure
  data/constraint migrations get their own revision. Details: `backend/migrations/README.md`.

## `app/shared/` utilities (cross-cutting)

`errors.py` problem+json · `guards.py` guard evaluator (no eval) · `jsonlogic.py` JsonLogic for
form visibleIf/compute · `config_schemas.py` camelCase base · `permissions.py` permission catalog ·
`paging.py` pagination · `ratelimit.py` rate limiting · `altcha.py`/`antiabuse.py` captcha ·
`i18n.py` locale · `xlsx.py` spreadsheet export.

**Related:** every `be-*` skill, `frontend`, `deploy`.
