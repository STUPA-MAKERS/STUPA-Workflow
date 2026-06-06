# Antragsplattform

Webplattform für Anträge eines studentischen Gremiums: Antragstellende reichen über
ein öffentliches Formular ein, Gremienmitglieder bearbeiten, stimmen ab und führen
Budgets — alles versioniert und lückenlos auditiert.

Monorepo, eine VM, `docker compose`. Intern läuft alles plain HTTP; TLS terminiert ein
**externer Nginx Proxy Manager** davor. Kein Cert-Handling, kein eingebauter Keycloak
im Stack.

Ausführliche Doku im [Wiki](https://github.com/frederikbeimgraben/antragsplattform/wiki).

## Stack

- **Backend** — Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
  arq-Worker. uvicorn mit `--proxy-headers`.
- **Frontend** — Angular 20 (TS strict, standalone), @ngx-formly, RxJS.
- **Daten** — PostgreSQL 16 (Config und Submissions als versioniertes JSONB),
  Redis 7 (arq-Broker, Rate-Limit, Altcha-Replay), MinIO (S3-Anhänge), ClamAV.
- **PDF** — `pytex`, ein interner Markdown→PDF-Renderer (tectonic).
- **Captcha** — ALTCHA Sentinel (self-hosted, Proof-of-Work).

## Was schon läuft

Das Backend ist funktional, nicht mehr Skelett. Implementiert und getestet:

- **Auth** — OIDC/Keycloak (Authorization Code + PKCE, Server-Session) und
  Magic-Link für Antragstellende (HMAC-gehashte Single-Use-Token). RBAC über Rollen,
  Permissions und zeitlich begrenzte Zuweisungen.
- **Forms** — Formulare als versioniertes JSON; Definition und Antworten werden gegen
  ein Schema validiert (inkl. `visibleIf`/Compute via JsonLogic).
- **Applications** — Antrag anlegen (öffentlich, Captcha + Rate-Limit + Payload-Cap),
  bearbeiten mit Versions-Diff, Timeline, Kommentare, DSGVO-Anonymisierung.
- **Flow** — deklarative Zustandsmaschine mit Guard-Evaluator (Whitelist-Operatoren,
  **kein `eval`**) und Transition-Actions (notify/webhook/exportPdf/budget/openVote/…).
- **Voting** — Quorum (Anzahl/Prozent), Mehrheiten (einfach/absolut/Zweidrittel),
  Tie-Break, Geheimwahl (Stimme von Identität getrennt).
- **Notifications** — Mail-Templates (Jinja2, sandboxed, DE/EN), Regeln
  (Event→Template→Empfänger), Versand über den arq-Worker.
- **Audit** — append-only Hash-Kette (`sha256(prev || canonical)`), DB-Trigger gegen
  UPDATE/DELETE, Ketten-Verifikation.
- **Budget** — Töpfe, Stages (requested→reserved→approved→paid), Überbuchungsschutz,
  Rollup-Statistiken via Materialized Views.

Roadmap (noch nicht gebaut): Sitzungs-/Protokoll-Modul, Live-Vote über WebSocket
(Frontend-Service steht, Server-Endpoint fehlt), die Frontend-Screens für
Applications/Voting/Meetings/Budget/Admin (aktuell gegatete Platzhalter), MinIO- und
ClamAV-Anbindung im Code, E2E-Suite (Playwright).

## Setup (lokal)

Voraussetzung: Docker + Docker Compose v2.

```bash
cd deploy
cp .env.example .env        # Werte einsetzen — siehe Wiki/Configuration
docker compose up -d --build
```

Migrationen laufen automatisch: ein One-Shot-`migrate`-Service spielt `alembic upgrade
head` ein, bevor `api` und `worker` starten. Danach ist die SPA unter
<http://127.0.0.1:8080/> erreichbar (einziger Host-Port). Liveness: `/healthz` (web),
`/api/health` (api).

> Beim ersten Start lädt ClamAV mehrere Minuten Signaturen (langes `start_period`).

## Repo-Layout

```
backend/    FastAPI-App, arq-Worker, Module, Migrationen, Tests
frontend/   Angular-SPA + Design-System
pytex/      Markdown→PDF-Renderer (FastAPI um tectonic)
deploy/     docker-compose.yml, web/ (nginx + Multi-Stage-Build), .env.example
scripts/    smoke.sh
```

## Entwicklung

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
npm run lint && npm run typecheck && npm test
```

TDD ist verbindlich, PRs müssen das CI-Gate grün passieren — Details in
[CONTRIBUTING.md](CONTRIBUTING.md). Nie direkt auf `main`. Secrets nur in
`deploy/.env` (per `.gitignore` geblockt), nie committen.

## Sicherheit (kurz)

Sessions als signierte HttpOnly-Cookies (`itsdangerous`), OIDC mit PKCE und
State/Nonce, Magic-Link-Token nur als HMAC-Hash gespeichert. Öffentliche Endpunkte
hinter ALTCHA und Redis-Rate-Limit. Audit-Log append-only auf DB-Ebene. RFC-9457
`application/problem+json` als Fehler-Contract. Mehr im
[Security-Wiki](https://github.com/frederikbeimgraben/antragsplattform/wiki/Security).
