# backend

FastAPI-API + arq-Worker. Python 3.13, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
uvicorn (`--proxy-headers`).

## Aufbau

```
app/
  main.py            App-Factory: Router unter /api, Middleware, Error-Contract
  settings.py        pydantic-settings; lädt .env, erzwingt Pflicht-Secrets
  db.py              async Engine/Session, DeclarativeBase, Mixins
  middleware.py      Trace-Id + Security-Header (CORS bewusst aus)
  shared/
    errors.py        RFC-9457 problem+json (ProblemDetail, Handler, OpenAPI-Rewrite)
    guards.py        Guard-Evaluator (Whitelist-Operatoren, kein eval)
    jsonlogic.py     JsonLogic-Evaluator für Form-visibleIf/compute
    config_schemas.py  camelCase-Basismodell (alias, extra=forbid)
  modules/
    auth/            OIDC (PKCE) + Magic-Link, Sessions, RBAC, OAuth2/MCP
    forms/           versionierte Formulare, Definition-/Antwort-Validierung
    application_types/ Antragstypen (Formular-/Flow-Bindung, Budget-Flag)
    applications/    Antrags-Lifecycle, Versions-Diff, Kommentare, Anonymisierung
    flow/            Zustandsmaschine, Guards, Transition-Actions
    voting/          Quorum/Mehrheiten/Geheimwahl, Tally (lesegescopt)
    livevote/        Sitzungen, Agenda, Anwesenheit, Live-Vote über WebSocket
    protocol/        Sitzungsprotokoll (Markdown → PDF), Vote-Snippets, Finalisierung
    delegations/     sitzungsgebundene Delegationen + Stellvertreter-Pool
    deadlines/       benannte Frist-Policies (vom Flow referenziert)
    budget/          Kostenstellen-Baum, HHJ, Zuteilung, Buchungen, Rechnungen (ZUGFeRD)
    files/           Upload, MIME-Sniff, ClamAV-Scan, MinIO/S3, signierte URLs
    pdf/             asynchroner Antrags-PDF-Render (pytex → MinIO)
    notifications/   Mail-Templates/Regeln, per-Nutzer-Präferenzen, arq-Versand
    webhooks/        ausgehende Event-Webhooks (SSRF-Guard, HMAC-Signatur)
    audit/           append-only Hash-Kette + Verifikation
    antiabuse/       Altcha-Challenge/-Verify, Rate-Limit, Payload-Cap
    admin/           Config-CRUD (Gremien, Rollen, Antragstypen, Branding, …),
                     eine Permission pro /admin/-Seite
migrations/          Alembic (0001–0026)
worker/              arq WorkerSettings: Mail/PDF/Scan-Tasks + nächtlicher Budget-Cron
tests/
```

Alle Router hängen unter `/api`. Modelle registrieren sich in `Base.metadata`; Alembic
zieht daraus. Antworten/Requests sind camelCase (per-Feld-Alias auf snake_case-Feldern).

## Lokal

```bash
pip install -e '.[dev]'
ruff check .                       # Lint
basedpyright                       # Typen, 0 Fehler erforderlich
pytest                             # Unit-Suite (kein Docker)
pytest --cov --cov-report=term-missing   # mit Coverage (Gate 85 %)
pytest -m integration              # testcontainers (Docker nötig)
```

Kritische Module (`auth`, `voting`, `flow`, `budget`, `webhooks`, `audit`) haben ein
eigenes Gate von 100 % Branch:

```bash
pytest --cov --cov-report=xml
python -m scripts.coverage_critical coverage.xml pyproject.toml
```

App ohne Compose starten (z. B. gegen lokale Postgres):

```bash
export DATABASE_URL=postgresql+asyncpg://app:pw@localhost/antrag
export SESSION_SECRET=... MAGIC_LINK_SECRET=...   # je ≥16 Zeichen
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

OpenAPI unter `/openapi.json`, Swagger-UI `/docs`. Konfiguration: siehe
[Configuration-Wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki/Configuration).
