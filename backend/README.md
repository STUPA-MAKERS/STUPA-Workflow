# backend

FastAPI API + arq worker. Python 3.13, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
uvicorn (`--proxy-headers`).

## Layout

```
app/
  main.py            app factory: routers under /api, middleware, error contract
  settings.py        pydantic-settings, loads .env, requires the mandatory secrets
  db.py              async engine/session, DeclarativeBase, mixins
  middleware.py      trace id + security headers (CORS off on purpose)
  shared/
    errors.py        RFC-9457 problem+json (ProblemDetail, handler, OpenAPI rewrite)
    guards.py        guard evaluator (whitelist operators, no eval)
    jsonlogic.py     JsonLogic evaluator for form visibleIf/compute
    config_schemas.py  camelCase base model (alias, extra=forbid)
  modules/
    auth/            OIDC (PKCE) + magic link, sessions, RBAC, OAuth2/MCP
    forms/           versioned forms, definition and answer validation
    application_types/ application types (form and flow binding, budget flag)
    applications/    application lifecycle, version diff, comments, anonymization
    flow/            state machine, guards, transition actions
    voting/          quorum/majorities/secret ballot, tally (scoped reads)
    livevote/        meetings, agenda, attendance, live vote over WebSocket
    protocol/        meeting protocol (Markdown → PDF), vote snippets, finalize
    delegations/     meeting-bound delegations + substitute pool
    deadlines/       named deadline policies (the flow references them)
    budget/          cost center tree, fiscal years, allocation, bookings, invoices (ZUGFeRD)
    files/           upload, MIME sniff, ClamAV scan, MinIO/S3, signed URLs
    pdf/             async application PDF render (pytex → MinIO)
    notifications/   mail templates and rules, per-user preferences, arq dispatch
    webhooks/        outgoing event webhooks (SSRF guard, HMAC signature)
    audit/           append-only hash chain + verification
    antiabuse/       ALTCHA challenge/verify, rate limit, payload cap
    admin/           config CRUD (Gremien, roles, application types, branding, …),
                     one permission per /admin/ page
migrations/          Alembic (0001–0026)
worker/              arq WorkerSettings: mail/PDF/scan tasks + nightly budget cron
tests/
```

All routers mount under `/api`. Models register themselves in `Base.metadata`, and Alembic
reads the schema from there. Requests and responses use camelCase. A per-field alias maps
each camelCase name to its snake_case field.

## Local

```bash
pip install -e '.[dev]'
ruff check .                       # lint
basedpyright                       # types, 0 errors required
pytest                             # unit suite (no Docker)
pytest --cov --cov-report=term-missing   # with coverage (85 % gate)
pytest -m integration              # testcontainers (Docker required)
```

The critical modules (`auth`, `voting`, `flow`, `budget`, `webhooks`, `audit`) have their own
gate of 100 % branch coverage:

```bash
pytest --cov --cov-report=xml
python -m scripts.coverage_critical coverage.xml pyproject.toml
```

Start the app without compose, for example against a local Postgres:

```bash
export DATABASE_URL=postgresql+asyncpg://app:pw@localhost/antrag
export SESSION_SECRET=... MAGIC_LINK_SECRET=...   # each at least 16 characters
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

OpenAPI sits at `/openapi.json`. Swagger UI sits at `/docs`. For configuration, see the
[Configuration wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki/Configuration).
