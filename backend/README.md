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
    auth/            OIDC (PKCE) + Magic-Link, Sessions, RBAC
    forms/           versionierte Formulare, Definition-/Antwort-Validierung
    application_types/ Antragstypen (Formular-/Flow-Bindung, Budget-Flag)
    applications/    Antrags-Lifecycle, Versions-Diff, Kommentare, Anonymisierung
    flow/            Zustandsmaschine, Guards, Transition-Actions
    voting/          Quorum/Mehrheiten/Geheimwahl, Tally
    budget/          Töpfe, Stages, Überbuchungsschutz, Rollup-Stats
    notifications/   Mail-Templates/Regeln, arq-Versand
    audit/           append-only Hash-Kette + Verifikation
    antiabuse/        Altcha-Challenge/-Verify, Rate-Limit, Payload-Cap
    admin/           Config-Modelle (Gremium, MailList, ApplicationType)
migrations/          Alembic (0001–0007)
worker/              arq WorkerSettings: send_mail + nächtlicher Budget-Rollup-Cron
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
[Configuration-Wiki](https://github.com/frederikbeimgraben/antragsplattform/wiki/Configuration).
