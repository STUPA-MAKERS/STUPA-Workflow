# Contributing — Antragsplattform

Binding workflow: **TDD (Red-Green-Refactor)**. The CI gate blocks pull requests
(`sds/testing.md`). This document collects the workflow, the Definition of Done and the
branch protection settings.

## TDD: Red → Green → Refactor

1. **Red** — Write the test first. It describes the wanted behavior. Run it. It *must
   fail*. A test that fails before the production code exists is a real test.
2. **Green** — Write the smallest amount of production code that makes the test pass.
   Write no more.
3. **Refactor** — Remove duplication and clutter. The tests stay green.

Do not use `skip` or `xfail` without a stated reason and a link to an issue.

## Local tests

Backend (`backend/`):

```bash
pip install -e '.[dev]'
ruff check .                       # Lint
basedpyright                       # Types (0 errors required)
pytest                             # fast unit suite (no Docker)
pytest --cov --cov-report=term-missing   # with coverage (gate 97 %)
pytest -m integration              # integration (testcontainers, Docker required)
```

Check the coverage gate of the critical modules (100 % branch) on your machine:

```bash
pytest --cov --cov-report=xml
python -m scripts.coverage_critical coverage.xml pyproject.toml
```

Frontend (`frontend/`):

```bash
npm ci
npm run lint
npx tsc --noEmit
npm test -- --coverage          # Gate: statements 98 %, branches 96 %, functions 98 %, lines 99 %
npx playwright test             # E2E against the compose stack
```

## Coverage gates (CI fails below the limit)

- Backend total **97 %** (lines and branches) — `[tool.coverage.report] fail_under`.
- Frontend: statements **98 %**, branches **96 %**, functions **98 %**, lines **99 %** —
  `jest.config` `coverageThreshold`.
- **100 % branch** for the critical modules (`auth`, `voting`, `flow`, `budget`,
  `webhooks`, `audit`) — a separate gate through `scripts/coverage_critical.py`. It
  applies as soon as the module exists.

## CI stages (`.github/workflows/ci.yml`)

The jobs start in parallel, as a flat fan-out, not one after another. The required jobs
are `be-lint`, `be-typecheck`, `be-unit`, `be-integration`, `be-contract` (Schemathesis),
`fe-unit`, `coverage-gate`, `image-build-smoke` (main pushes only), `pytex` and
`compose`. `e2e` (Playwright against the compose stack), `restore-smoke` and
`real-stack-smoke` stay opt-in. A label, a manual run or a repo variable starts them. A
red pull request stays blocked.

## Definition of Done (per task or module)

The checklist in the pull request template (`.github/pull_request_template.md`) is
binding. It asks in advance about our recurring review errors. Each item stands for an
error that already cost us at least once. The same items follow as prose. Each one
carries a short *why*:

- **tz-aware (timestamptz, no mix of naive and aware).** Use `timestamptz` for every
  timestamp in the database and an aware `datetime` in Python (`datetime.now(UTC)`,
  never `utcnow()`). *Why:* a naive value from a migration or a seed already crashed
  RBAC (`can't compare offset-naive and offset-aware`). That fault then caused a
  meeting WebSocket 403. A single naive value poisons every comparison.
- **problem+json on ALL error paths.** Every 4xx and 5xx returns
  `application/problem+json`. This also holds for a branch you add later. *Why:* the
  contract tests (Schemathesis) and the frontend expect one error schema. A bare string
  or the FastAPI default `detail` breaks both. A local visual check misses it easily.
- **RBAC enforced on the server, no privilege escalation.** The backend checks the
  permission. Frontend gating alone is not enough. Roles and owner come from the
  session, never from the request body. *Why:* frontend gating gives comfort, not
  security. A caller that hits the route directly goes around it. An object owner that
  differs from the caller is the most frequent leak.
- **Same names in the frontend and backend contract.** Use the same field, header and
  cookie names on both sides. Use **camelCase** in JSON. *Why:* drift between
  `snake_case` and `camelCase` comes back again and again. So do frontend fields that
  the backend never had. Both sides compile and then fail silently at run time.
- **Strictly typed inputs (enums and literals instead of free strings).** Validate
  query, body and path through Pydantic and `Annotated`. Model a status field as an enum
  or a `Literal`. *Why:* an open `str` status field accepts typos and invalid
  transitions. The error then breaks out deep in the code. The `lang` parameter was such
  a case. It was free text instead of `de|en`.
- **i18n de/en parity.** Add every new string to both locales. Hard-code nothing.
  *Why:* a missing `en` key stays invisible in the German UI. It appears in the English
  UI as a raw key.
- **a11y.** Labels and `aria-*`, focus order, keyboard, contrast.
- **Dark and light.** Check both themes. *Why:* fixed colors break in the other theme
  again and again. The production build (inlineCritical) also behaves differently from
  the dev build. Check against the **production** build.
- **Frontend self-check with the visual harness (before and after).** Create the
  screenshots and *look* at them, one set per theme. *Why:* "it probably looks fine" is
  not a self-check. Most layout regressions show up only in the screenshot.
- **Single migration head.** `alembic heads` shows one head. `alembic upgrade head` runs
  green. See "Database migrations (Alembic)" below.

Plus the hard gates:

- Tests written first, all green.
- Coverage gate held (module-specific for the critical modules).
- `ruff` and `basedpyright` (BE), `eslint` and `tsc` (FE) green.
- Contract tests green, affected E2E tests green.
- No `skip` or `xfail` without a linked reason.

## Database migrations (Alembic)

**A new migration uses `alembic revision` with a hash id** (the Alembic default).
`down_revision` points to the current head. The old sequential `000N` convention is
gone.

```bash
cd backend
alembic revision -m "short_description"  # creates for example aa50a10a8072_short_description.py
alembic heads                            # MUST show exactly one head
alembic upgrade head                     # MUST run green
```

*Why a hash and not `000N`:* parallel work waves picked the same next number on their
own (`0016` collided twice). Every merge then forced a renumbering by hand. Random
hashes almost never collide. The head comparison (the single-head gate) stays the only
merge conflict point. That conflict is visible on purpose.

Rules:

- **No `--rev-id`, no `000N` prefixes** any more. Alembic assigns the hash id.
- **Existing migrations keep their names.** The `0001…0048` chain stays as it is. Only
  *new* revisions get hash ids.
- `down_revision` points to the **current** head. `alembic revision` does this for you
  as long as exactly one head exists.
- Tables and models still come from `Base.metadata.create_all` in `0002` (single-source
  pattern). A pure data or constraint migration gets its own revision.
- Details: `backend/migrations/README.md`.

## Branch protection (`main`)

Set this for `main` under **Settings → Branches → Branch protection rule**:

- ✅ **Require a pull request before merging** (≥ 1 review).
- ✅ **Require status checks to pass before merging** → *Require branches up to date*.
  Required checks (job names from `ci.yml`):
  `be-lint`, `be-typecheck`, `be-unit`, `be-integration`, `be-contract`, `fe-unit`,
  `coverage-gate`, `image-build-smoke`, `pytex`, `compose`.
  `e2e` stays opt-in (see "CI stages" above) and is not a required check.
- ✅ **Require conversation resolution before merging**.
- ✅ **Do not allow bypassing the above settings** (admins included).
- 🚫 Turn off force push and branch deletion.

## Pre-commit

```bash
pip install pre-commit && pre-commit install
```

This runs `ruff` (lint and format) and `basedpyright` before every commit
(`.pre-commit-config.yaml`).
