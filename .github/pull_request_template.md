<!--
Definition of Done — go through the list BEFORE the review. The list checks the
error classes that come back again and again in our reviews. Each box stands for a
mistake that already cost us at least once. Tick a point that does not apply to this
pull request as `[x] n/a — <short reason>`. Do not delete the point. The reason for
each point is in docs/CONTRIBUTING.md / CONTRIBUTING.md → "Definition of Done".
-->

## What and Why

<!-- Short: what changes, which issue or task (T-/#), and why this way. -->

Closes #

## Definition of Done

### Backend / Contract
- [ ] **tz-aware** — every timestamp is `timestamptz` in the DB and an aware `datetime` in Python. **No** naive/aware mix. No `datetime.utcnow()` (use `datetime.now(UTC)`).
- [ ] **problem+json on ALL error paths** — every 4xx/5xx returns `application/problem+json`, new paths and branches included. No bare string and no default FastAPI `detail`.
- [ ] **RBAC enforced server-side** — the backend checks the permission, not only the frontend gating. No privilege escalation: the object owner can differ from the caller, and roles from the request stay untrusted.
- [ ] **Inputs strictly typed** — enums or `Literal` instead of free strings. Query, body and path are validated (Pydantic / `Annotated`). No open `str` status fields.
- [ ] **Migration single-head** — `alembic heads` shows **one** head, `alembic upgrade head` runs green. A new revision gets a **hash id** (`alembic revision`, never `--rev-id`/`000N`). Its `down_revision` is the current head.
- [ ] **Contract tests green** — Schemathesis (`--checks all`) stays green. OpenAPI mirrors the change.

### FE/BE contract (same names)
- [ ] **Field, header and cookie names identical** FE↔BE, **camelCase** in the JSON. No field invented by the frontend. No silent renames (`snake_case`↔`camelCase` drift).

### Frontend / UX
- [ ] **i18n de/en parity** — every new string is in **both** locales (`de` + `en`). No hardcoded text.
- [ ] **a11y** — labels and `aria-*`, focus order, keyboard operation, contrast.
- [ ] **Dark/light** — checked in **both** themes. No fixed colors that break in the other theme.
- [ ] **Frontend self-check with the visual harness** — before/after screenshots taken and reviewed, no "looks fine to me". Link or attach the affected screens below.

### Tests & Gates
- [ ] Tests written test-first, all green. The coverage gate holds (critical modules 100 % branch).
- [ ] `ruff` + `basedpyright` (BE) / `eslint` + `tsc` (FE) report **0** errors.
- [ ] No `skip` or `xfail` without a linked reason.

## Screenshots (before / after)

<!-- Visual-harness output for the affected screens, one per theme. -->
