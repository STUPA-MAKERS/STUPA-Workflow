# STUPA-Workflow

Webplattform für die Antrags-, Sitzungs- und Budgetarbeit eines studentischen
Gremiums (StuPa/AStA): Antragstellende reichen über ein öffentliches Formular ein,
Gremienmitglieder bearbeiten Anträge, führen Sitzungen mit Live-Abstimmungen und
Protokoll, verwalten Kostenstellen-Budgets und Rechnungen — alles versioniert und
lückenlos auditiert.

Monorepo, eine VM, `docker compose`. Intern läuft alles plain HTTP; TLS terminiert ein
**externer Nginx Proxy Manager** davor. Kein Cert-Handling, kein eingebauter Keycloak
im Stack.

Ausführliche Doku im [Wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki).

## Stack

- **Backend** — Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async) + Alembic,
  arq-Worker. uvicorn mit `--proxy-headers`, läuft als Non-Root-Container.
- **Frontend** — Angular (TS strict, standalone components, separate `.html`/`.scss`),
  @ngx-formly, RxJS, Signals.
- **Daten** — PostgreSQL 16 (Config und Submissions als versioniertes JSONB),
  Redis 7 (arq-Broker, Rate-Limit, Altcha-Replay), MinIO (S3-Anhänge/Belege), ClamAV.
- **PDF** — `pytex`, ein interner Markdown→PDF-Renderer (tectonic), egress-isoliert.
- **Captcha** — ALTCHA Sentinel (self-hosted, Proof-of-Work).

## Funktionsumfang

Backend funktional und getestet (~1480 Unit-Tests + Integrations-Suite). Implementiert:

- **Auth & RBAC** — OIDC/Keycloak (Authorization Code + PKCE, Server-Session) und
  Magic-Link für Antragstellende (HMAC-gehashte Single-Use-Token). Rollen, Permissions
  und zeitlich begrenzte Zuweisungen; eine eigene Permission **pro `/admin/`-Seite**.
- **Forms** — Formulare als versioniertes JSON; Definition und Antworten gegen ein
  Schema validiert (inkl. `visibleIf`/Compute via JsonLogic, ReDoS-gehärtete Patterns).
- **Applications** — Antrag anlegen (öffentlich, Captcha + Rate-Limit + Payload-Cap),
  bearbeiten mit Versions-Diff, Timeline, Kommentare, DSGVO-Anonymisierung.
- **Flow** — deklarative Zustandsmaschine mit Guard-Evaluator (Whitelist-Operatoren als
  Dispatch-Tabelle, **kein `eval`**) und Transition-Actions (notify/webhook/exportPdf/
  budget/openVote/…).
- **Voting** — Quorum (Anzahl/Prozent), Mehrheiten (einfach/absolut/Zweidrittel),
  Tie-Break, Geheimwahl (Stimme von Identität getrennt). Lesezugriff gremium-gescopt.
- **Meetings / LiveVote** — Sitzungen mit Agenda, Anwesenheit und Live-Abstimmung über
  WebSocket (Voter-Kanal + read-only Beamer-Stream); Protokoll entsteht beim Start.
- **Protocol** — Sitzungsprotokoll (Markdown), Abstimmungen als Snippets, asynchroner
  PDF-Render (pytex → MinIO) + Mail-Versand beim Finalisieren.
- **Delegations** — sitzungsgebundene Stimm-/Vertretungs-Delegationen + Stellvertreter-Pool.
- **Budget** — hierarchischer Kostenstellen-Baum mit Haushaltsjahren, Top-Down-Zuteilung,
  Buchungen/Umbuchungen, Konten und **Rechnungen mit ZUGFeRD/Factur-X-Import**.
  Alle Geldmutationen werden auditiert.
- **Notifications** — Mail-Templates (Jinja2, sandboxed, DE/EN), Regeln
  (Event→Template→Empfänger), per-Nutzer-Präferenzen, Versand über den arq-Worker.
- **Audit** — append-only Hash-Kette (`sha256(prev || canonical)`), DB-Trigger gegen
  UPDATE/DELETE, Ketten-Verifikation.
- **Webhooks** — ausgehende Event-Webhooks mit SSRF-Guard (private/Loopback/Link-Local/
  NAT64-Ziele blockiert, DNS-Rebind-Pinning) und HMAC-Signatur.

Frontend: Screens für Applications, Voting, Meetings, Budget/Expenses/Invoices und die
Admin-Konfiguration (Forms, Flow, Gremien, Rollen, Branding, …).

Offen / Roadmap: erweiterte E2E-Suite (Playwright), weitere Flow-Action-Handler.

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
mcp/        MCP-Server (Agent-/API-Zugang)
deploy/     docker-compose.yml, web/ (nginx + Multi-Stage-Build), .env.example, backup/
scripts/    Hilfs-Skripte (smoke, Rollen-Pflege)
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
npm run lint && npm run typecheck && npm test && npm run build
```

TDD ist verbindlich; PRs müssen das CI-Gate grün passieren — Details in
[CONTRIBUTING.md](CONTRIBUTING.md). Nie direkt auf `main`. Secrets nur in
`deploy/.env` (per `.gitignore` geblockt), nie committen.

## Branching & Releases

Trunk-basiert mit geschütztem `main` und tag-basierter Auslieferung — bewusst leicht
gehalten (kein langlebiger `develop`-Branch, kein GitFlow-Overhead für ein
Single-VM-Deployment).

| Branch | Zweck | Regeln |
|---|---|---|
| `main` | immer grün, immer deploybar | **protected**: PR + grünes CI + 1 Review, kein direkter Push, linear history |
| `feat/*`, `fix/*`, `chore/*`, `docs/*` | kurzlebige Arbeitszweige ab `main` | via PR mergen (squash), nach Merge löschen |
| `hotfix/*` | dringender Prod-Fix ab dem laufenden Release-Tag | PR → `main`, danach neuer Patch-Tag |

**Releases.** Produktion läuft auf einem **Tag**, nicht auf `main`-HEAD. Versionen nach
SemVer: `vMAJOR.MINOR.PATCH`. Ein Release wird auf `main` getaggt; CI baut die Images,
markiert sie mit dem Tag und deployt. So ist jederzeit reproduzierbar, welcher Stand
produktiv ist, und ein Rollback ist ein Re-Deploy des Vorgänger-Tags.

```
feat/x ──PR──▶ main ──tag v1.2.0──▶ Build+Deploy
                 ▲
hotfix/y ──PR────┘  (ab v1.2.0)  ──tag v1.2.1──▶ Deploy
```

**DB-Migrationen** sind Teil des Releases: additive/abwärtskompatible Alembic-Schritte
bevorzugen (erst Spalte hinzufügen, später Altlast entfernen), damit ein Rollback der
App nicht an der DB scheitert. Revisions-IDs ≤ 32 Zeichen.

Empfohlene Branch-Protection für `main`: „Require a pull request before merging" (1
Approval), „Require status checks to pass" (CI: ruff + basedpyright + pytest + ng build
+ jest), „Require linear history", „Require branches to be up to date".

## Sicherheit (kurz)

Sessions als signierte HttpOnly-Cookies (`itsdangerous`), OIDC mit PKCE und
State/Nonce, Magic-Link-Token nur als HMAC-Hash gespeichert. Öffentliche Endpunkte
hinter ALTCHA und Redis-Rate-Limit. Ausgehende Webhooks hinter einem SSRF-Guard.
Audit-Log append-only auf DB-Ebene. RFC-9457 `application/problem+json` als
Fehler-Contract. Mehr im
[Security-Wiki](https://github.com/STUPA-MAKERS/STUPA-Workflow/wiki/Security).
