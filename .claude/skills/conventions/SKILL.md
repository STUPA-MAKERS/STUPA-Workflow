---
name: conventions
description: STUPA-Workflow house rules, Definition-of-Done, test/coverage gates, alembic migration policy, and the shared/ backend utilities (problem+json, guards, jsonlogic, RBAC). Read this FIRST before changing backend or frontend code, opening a PR, or writing a migration. Use when unsure how this repo expects code, errors, types, i18n, or DB migrations to be done.
---

# Project conventions — house rules & Definition of Done

The non-negotiables. Source of truth: this skill, `.github/pull_request_template.md`,
`backend/migrations/README.md`. Each rule encodes a bug that already cost the team once.

## Workflow

- **TDD: Red → Green → Refactor.** Write the failing test first, then minimal code, then clean up.
  No `skip`/`xfail` without a written reason.
- **Finish the job:** branch → commit → push → PR, then watch CI and fix failures.
- **Ask before design decisions.** A fork with more than one reasonable answer goes to the user.

## Backend Definition of Done

- **tz-aware everywhere** — `timestamptz` in DB, aware `datetime` in Python (`datetime.now(UTC)`, never
  `utcnow()`). A single naive value poisons every comparison (has crashed RBAC + caused WS 403s).
- **problem+json on ALL error paths** — every 4xx/5xx returns `application/problem+json` (RFC-9457),
  including new branches. `app/shared/errors.py` holds the implementation (`ProblemDetail`, the
  handlers and the OpenAPI rewrite). Never return a bare string or the default `detail` of FastAPI.
- **RBAC enforced server-side** — check the permission in the backend, not just in FE gating. Roles and
  owner come from the session, never the request body. Object-owner ≠ caller is the most common leak.
  See `[[admin-domain-rules]]`. Where each check goes: global permission → route gate
  (`require_principal("perm")`); gremium permission → `app/modules/auth/policy.py`; object rule →
  bare gate plus an entry in `OBJECT_CHECK_ROUTES` (`backend/tests/unit/test_route_gates.py`).
  Details in `be-auth`.
- **Strictly typed inputs** — Enums/`Literal` instead of free strings. Validate query/body/path via
  Pydantic/`Annotated`. No open `str` status fields. Python ≥3.13, fully annotated, no bare `Any`
  (basedpyright runs in `standard` mode).
- **Docstrings, not comments** — every public module, class and function in `app/`, `worker/`,
  `scripts/` and `migrations/` has a brief Google-style docstring (ruff `D`, google convention).
  Tests may omit them, but the ones they have follow the same format. A `#` comment in a code body
  is the rare exception for a trick the code cannot show. A reason goes into the docstring, with
  its "because" kept. Never refer to old tasks, issues or spec sections; state the rule itself.
- **No `eval`** — flow/form guards run through a whitelist dispatch table (`app/shared/guards.py`,
  `app/shared/jsonlogic.py`), never `eval`.

## Functional style

The rules are the specs in `specs/style/shared/functional/` (000081-000089, 000437),
`specs/style/backend/functional/000090` and `specs/style/frontend/functional/` (000091, 000438).
Read them before you change code. In short:

- **Body shape:** guard raises, then locals bound once, then one `return` of an expression or one
  `match`/`switch` with a `return` per case. Readability limits the single expression: split
  anything deeper than three levels or longer than 8 lines into named locals or a helper.
- **No rebinding, no mutation:** no second assignment, no `+=`, no `.append`/`.add`/`x[k] = v`
  (Python), only `const`, no `.push`/`.splice`/in-place `.sort()` (TS). Build the value whole:
  comprehension, generator into `tuple()`/`dict()`/`sum()`, spread, `dataclasses.replace`,
  `model_copy(update=...)`, `toSorted()`.
- **Loops:** a loop that builds a value is a comprehension or `map`/`filter`/`flatMap`/`reduce`,
  never `forEach`. A loop that only causes effects (send mails) stays a `for` statement.
- **Branches:** a branch on one value with two or more outcomes is an exhaustive `match`
  (`assert_never`) or `switch` (`assertNever` from `shared/util/immutable.ts`). A binary choice is a
  conditional expression, nested at most one level. basedpyright `reportMatchNotExhaustive` is on.
- **Frozen data:** `@dataclass(frozen=True, slots=True)`; every Pydantic model is frozen through
  `FrozenModel`/`FrozenCamelModel`/`FrozenStrictCamelModel` in `app/shared/schemas.py`, and each
  subclass repeats `frozen=True` (basedpyright demands it). Fields are `tuple`, `frozenset`,
  `Mapping`. TS: `readonly` fields, `readonly T[]`, `ReadonlySet`, `ReadonlyMap`, `as const`.
- **Effects at the edge:** DB, Redis, S3, mail, audit and WebSocket calls stay in services,
  routers and Angular services; the decision is a pure function next to them. Never
  `asyncio.gather` over one `AsyncSession`; use `[await f(x) for x in xs]`.
- **Signals:** `computed()` is a pure expression; `.update(fn)` gets a pure `fn`
  (`(s) => toggled(s, key)`), never copy-then-mutate.
- **Exceptions (000089):** ORM rows and migrations, tests, `try`/`with`/`raise`, Pydantic
  validators and framework wiring, signals in event handlers, ngx-formly configs and Reactive
  Forms, DOM APIs and RxJS subscriptions.
- **Reference examples:** `_majority` in `backend/app/modules/voting/tally.py` (match per case) and
  `linkSub` in `frontend/src/app/features/todos/todos.util.ts` (switch that returns, after its refactor).

**Enforcement.** ruff selects `C4`, `PERF401`, `PERF402`, `SIM108`, `RET`, `PLW2901`, `FURB`
(tests and migrations excepted). ESLint runs `eslint-plugin-functional` and `prefer-const`,
`no-param-reassign`, `switch-exhaustiveness-check` as warnings on `src/**` (no specs).
`scripts/check_functional.py` counts the violations per file against
`scripts/functional-baseline/<area>.json` (one file per backend module and frontend folder); CI
(`functional` job, and the ratchet step of `fe-unit`) fails when a count differs. After you lower a
count, run:

```sh
python3 scripts/check_functional.py --write                     # backend, mcp, typst
(cd frontend && npx eslint . -f json -o eslint-report.json) && \
  python3 scripts/check_functional.py --eslint frontend/eslint-report.json --write
```

## FE/BE contract

- **Identical field/header/cookie names** FE↔BE, **camelCase** in JSON. No FE-invented fields, no silent
  `snake_case`↔`camelCase` drift — both sides compile, then they fail silently at runtime.
- camelCase base model: `FrozenCamelModel` in `app/shared/schemas.py` (frozen, `populate_by_name`);
  `FrozenStrictCamelModel` adds `extra=forbid`.

## Frontend Definition of Done

- **i18n de/en parity** — every new string in BOTH locales, nothing hardcoded. Edit EN too
  (`[[admin-domain-rules]]`).
- **a11y** — labels/`aria-*`, focus order, keyboard, contrast.
- **Dark/Light** — verify in both themes. Check against the **prod** build (inlineCritical differs from
  dev).
- **Run `npm run build`** after CSS changes — bundle/style budgets fail the Docker build but pass jest+tsc
  (`[[ng-build-budgets]]`).
- UI conventions: `[[empty-state-convention]]`, `[[no-uuids-in-ui]]`,
  `[[loading-bar-convention]]`, `[[tailwind-preflight-off-borders]]`, `[[mobile-view-decisions]]`.

## Tests & coverage gates (CI blocks on these)

- Backend ≥ **97 %** (lines + branches). Frontend: statements **98 %**, branches **96 %**, functions
  **98 %**, lines **99 %**.
- **100 % branch** for critical modules: `auth`, `voting`, `flow`, `budget`, `webhooks`, `audit`,
  `backup` (`scripts/coverage_critical.py`, list in `[tool.coverage_critical]` of
  `backend/pyproject.toml`).
- Local (BE): `ruff check .` + `basedpyright` (0 errors) + `pytest`. Local (FE): `npm run lint`,
  `npm run typecheck`, `npm test`. CI order: `Lint → Typecheck → BE-Unit → BE-Integration →
  Contract (Schemathesis) → FE-Unit → E2E (Playwright) → Coverage-Gate → Image-Build + Smoke`.
  The `mcp` job (ruff check + pytest of `mcp/`) and the `typst` job run beside them.

## Alembic migrations

- New revision = **hash id** (`cd backend && alembic revision -m "..."`), NOT the old `000N` prefix and
  **no `--rev-id`**. The `0001…0048` chain stays as-is. Only new revisions get hash ids.
- `alembic heads` MUST show exactly one head. `alembic upgrade head` MUST be green. Single-head is the
  one intended merge-conflict point.
- Revision ids MUST be ≤ 32 chars (`alembic_version varchar(32)`). A longer id passes `alembic heads`
  locally, then fails the deploy at `UPDATE alembic_version` with `StringDataRightTruncationError`.
  A hash id (12 chars) always fits; mind the length only for a hand-written id.
- The `0001` baseline creates the whole schema via `Base.metadata.create_all` (single-source). Pure
  data/constraint migrations get their own revision. Details: `backend/migrations/README.md`.
- **A migration that adds a table MUST be idempotent.** The baseline builds from
  `Base.metadata`, so the moment the model is registered in `app/models.py` the table already
  exists at `0001` on a fresh database. A plain `op.create_table` then fails the FIRST
  `alembic upgrade head` with `relation "<table>" already exists`, and only on a clean database,
  so a local run against an existing one will not catch it. Use raw
  `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` and `DROP TABLE IF EXISTS`, as
  `0007_oauth_tokens`, `0035`, `0037` and `f3b3f1a022b5` do.

## `app/shared/` utilities (cross-cutting)

`errors.py` problem+json · `guards.py` guard evaluator (no eval) · `jsonlogic.py` JsonLogic for
form visibleIf/compute · `config_schemas.py` camelCase base · `permissions.py` permission catalog ·
`paging.py` pagination · `ratelimit.py` rate limiting · `altcha.py`/`antiabuse.py` captcha ·
`i18n.py` locale · `search.py` trigram/ILIKE fuzzy search of the list services · `xlsx.py` spreadsheet export · `ssrf.py` SSRF guard of the outgoing requests (webhooks, Gravatar; 100 % branch gate) · `filenames.py` upload display/storage names and
`Content-Disposition` (see `be-files`).

**Related:** every `be-*` skill, `frontend`, `deploy`.
