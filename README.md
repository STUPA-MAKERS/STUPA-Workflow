# Antragsplattform

Monorepo für die VS-Antragsplattform (Anträge, Voting/Live-Vote, Sitzungsprotokolle,
Budget, PDF-Export). Eine VM, `docker compose`, plain HTTP intern hinter externem
**Nginx Proxy Manager** (TLS-Edge). Kein TLS/Cert/Keycloak im Stack.

> **Stand:** Skelett (T-01). Lauffähige Compose-Topologie + Platzhalter-Services.
> Backend/Frontend/Module folgen in T-02ff.

## Stack

- **Backend:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
  arq (Worker), uvicorn (`--proxy-headers`).
- **Frontend:** Angular (TS strict), @ngx-formly, rete.js/@foblex/flow, RxJS.
- **DB:** PostgreSQL 16 · **Cache/Broker/PubSub:** Redis 7 · **Storage:** MinIO (S3)
  · **Virenscan:** ClamAV · **Captcha:** Altcha · **PDF:** pytex (md→pdf).
- **Edge:** externer Nginx Proxy Manager (TLS); intern `web`-nginx serviert SPA +
  routet `/api`.

## Repo-Layout

```
backend/    FastAPI app + arq worker + (später) Module, Migrationen, Tests
frontend/   Angular-SPA + Design-System (T-03)
pytex/      Dockerfile + FastAPI-Wrapper render_blob (T-21)
deploy/     docker-compose.yml, web/nginx.conf, .env.example
scripts/    smoke.sh (Healthcheck-Smoke)
```

## Services (deploy/docker-compose.yml)

`web` (nginx, einziger Host-Port `127.0.0.1:8080`) · `api` (FastAPI) ·
`worker` (arq) · `postgres` · `redis` · `minio` · `clamav` · `pytex` · `altcha`.
Außer `web` published **kein** Service Host-Ports → kein Internet-Ingress; Egress
für `worker`/`pytex`/`api` bleibt offen.

## Setup (lokal / dev)

Voraussetzung: Docker + Docker Compose v2.

```bash
cd deploy
cp .env.example .env        # Werte einsetzen (Passwörter/Keys)
docker compose config -q    # Topologie validieren
docker compose up -d --build
```

`web` dann erreichbar unter <http://127.0.0.1:8080/>. Liveness: `/healthz` (web),
`/health` (api, pytex).

### Smoke-Test

```bash
scripts/smoke.sh        # up + wartet bis alle Services healthy
scripts/smoke.sh down   # Stack inkl. Volumes abräumen
```

> Hinweis: ClamAV lädt beim ersten Start die Signaturen (mehrere Minuten) → langes
> `start_period`. MinIO/ClamAV-Startzeiten sind das bekannte Timing-Risiko (T-01).

## Backend-Entwicklung

```bash
cd backend
pip install -e '.[dev]'
ruff check . && basedpyright && pytest
```

## Konventionen

- **Branch + PR**, niemals direkt auf `main` (Ausnahme: initialer Scaffold-Commit T-01).
  Branch-Schema `feat/T-XX-<slug>`.
- **TDD** test-first; DoD: Tests grün + Coverage-Gate + `ruff`/`basedpyright` (BE) /
  `eslint`/`tsc --strict` (FE) grün. Kein sudo.
- Secrets nur in `deploy/.env` (nie committen).

## Sicherheit

`.env` enthält Datenbank-, OIDC-, SMTP-, Webhook- und Storage-Secrets und darf **nie**
ins Repo. `.gitignore` blockt `deploy/.env`. TLS terminiert ausschließlich der externe
Nginx Proxy Manager.
