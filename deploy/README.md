# deploy

Compose-Stack für eine VM. Plain HTTP intern; TLS terminiert der externe Nginx Proxy
Manager. Einziger Host-Port ist `web` auf `127.0.0.1:8080` — alle anderen Services
hängen nur am internen Netz und sind nicht vom Internet erreichbar.

## Start

```bash
cp .env.example .env        # Werte einsetzen, NIE committen
docker compose config -q    # Topologie validieren
docker compose up -d --build
```

## Services

| Service | Rolle | Host-Port |
|---|---|---|
| `web` | nginx, serviert die gebaute SPA, routet `/api` → `api` | `127.0.0.1:8080` |
| `migrate` | One-Shot: `alembic upgrade head`, dann Exit | — |
| `api` | FastAPI (uvicorn `--proxy-headers`) | — |
| `worker` | arq (Mail-Versand, nächtlicher Budget-Rollup) | — |
| `postgres` | PostgreSQL 16 | — |
| `redis` | Redis 7 (arq-Broker, Rate-Limit, Altcha-Replay) | — |
| `minio` | S3-Objektspeicher (Anhänge) | — |
| `clamav` | Virenscan (langer erster Start: Signaturen) | — |
| `pytex` | interner Markdown→PDF-Renderer | — |
| `altcha` | ALTCHA Sentinel (Captcha-Verifier) | — |
| `backup` | tägliches verschlüsseltes Backup (pg_dump + MinIO-Spiegel, age); Profil `prod`/`backup` | — |

`web` wird über das `..`-Repo-Root in zwei Stufen gebaut (`web/Dockerfile`): Stage 1
baut mit Node das Angular-Frontend, Stage 2 serviert es per nginx. `web/nginx.conf` ist
ins Image gebacken, aber zusätzlich gemountet — so lassen sich prod-Edits (z. B.
`real_ip`-CIDR des Proxy Managers) ohne Rebuild machen.

## Migrationen

`migrate` läuft einmalig vor `api`/`worker` (beide haben
`depends_on: migrate: service_completed_successfully`). `alembic upgrade head` ist
idempotent — schon eingespielte Revisionen werden übersprungen. Kein manueller
Migrationsschritt nötig, auch nicht beim Update: `docker compose up -d --build` zieht
das neue Image und `migrate` spielt offene Revisionen ein, bevor die App hochfährt.

Optional läuft `migrate` unter einem eigenen DB-User (`DB_MIGRATION_URL`), getrennt vom
Laufzeit-User der App.

### Least-Privilege-DB-Rollen (security.md §4/§10) — MANUELLER Prod-Schritt

> ⚠️ **Nicht automatisch.** Compose fährt nur `alembic upgrade head` (DDL/DML); es
> legt **keine** Rollen an und entzieht **keine** Grants. Ohne diesen Schritt läuft die
> Plattform funktional, aber **ohne** Rollentrennung — der Runtime-User könnte dann das
> Audit-Log per UPDATE/DELETE manipulieren (der Append-only-Trigger aus Migration 0006
> blockt das zwar rollenunabhängig, aber die Least-Privilege-Schicht fehlt). In Prod
> daher Pflicht.

`db/roles.sql` provisioniert die getrennten Service-User (`app` Runtime, `migrator`
DDL, optional `audit_writer`) und entzieht dem Runtime-User UPDATE/DELETE/TRUNCATE auf
`audit_entry`. **Einmalig als DB-Superuser** ausführen — Schritte 1–4 **vor**, Schritt 5
**nach** `alembic upgrade head` (idempotent, mehrfach gefahrlos):

```bash
# 1) Rollen anlegen (vor den Migrationen)
psql -U postgres -d antrag -f db/roles.sql
# 2) Passwörter aus dem Secret-Store setzen
psql -U postgres -d antrag -c "ALTER ROLE app PASSWORD '…'; ALTER ROLE migrator PASSWORD '…';"
# 3) Migrationen unter migrator (DB_MIGRATION_URL) laufen lassen — via compose-migrate
#    oder manuell: alembic upgrade head
# 4) Audit-Grant-Entzug erneut anwenden (Schritt 5 in roles.sql, jetzt existiert audit_entry)
psql -U postgres -d antrag -f db/roles.sql
```

Danach in `.env`: `DATABASE_URL` → User `app`, `DB_MIGRATION_URL` → User `migrator`.

## Netze

- `internal` — bridge, keine publizierten Ports → kein Ingress. Egress bleibt offen
  (Worker: SMTP/WebDAV/Webhooks, pytex: tectonic-Bundle, api: OIDC).
- `proxy` — in prod das vom Nginx Proxy Manager verwaltete Netz; dort `external: true`
  setzen und das NPM-Netz referenzieren.

## Konfiguration

Alle Secrets in `.env` (Vorlage: `.env.example`). Pflichtwerte für den API-Start:
`DATABASE_URL`, `SESSION_SECRET`, `MAGIC_LINK_SECRET`. OIDC, SMTP und Altcha aktivieren
sich, sobald ihre Werte gesetzt sind — fehlen sie, bleiben die jeweiligen Funktionen
sauber abgeschaltet (kein Crash). Vollständige Referenz im
[Configuration-Wiki](https://github.com/frederikbeimgraben/antragsplattform/wiki/Configuration).

### Bootstrap initialer Admins (#70) — Pflichtschritt bei echter OIDC-Auth

Unter echter OIDC-Auth (ohne Mock) hat ein frisches Schema **keinen** Admin: niemand
besitzt `admin.*`, also kann auch niemand über die Rollen-/Rechte-UI (`/admin/users`)
Rollen vergeben. Damit sich die Plattform nicht selbst aussperrt, weist der
Bootstrap-Mechanismus den/die ersten Admin(s) per OIDC-Subject **oder** E-Mail
idempotent die `admin`-Rolle zu — **beim Login** (OIDC-Callback) und **beim Startup**:

```dotenv
# kommagetrennt; mind. einen der beiden setzen
BOOTSTRAP_ADMIN_SUBJECTS=f47ac10b-58cc-4372-a567-0e02b2c3d479,kc|alice
BOOTSTRAP_ADMIN_EMAILS=admin@hochschule.example,vorstand@stupa.example
```

- **Subject** = der OIDC-`sub`-Claim aus Keycloak (stabil, fälschungssicher) — **bevorzugt**.
- **E-Mail** = der `email`-Claim (case-insensitiv). Greift **nur, wenn das id_token
  `email_verified: true` führt** — sonst könnte auf einem IdP/Realm mit Self-Registration
  ohne Mail-Verifikation jemand einen Token mit `email` = Bootstrap-Adresse minten und so
  Admin werden. Der E-Mail-Bootstrap wird daher **am Login** ausgewertet (frischer,
  verifizierter Claim); der **Startup-Sweep matcht ausschließlich per `sub`** (die
  gespeicherte `principal.email` trägt kein Verifikations-Flag). Praktisch: ein per E-Mail
  bootstrappter Admin erhält die Rolle bei seinem **nächsten Login**.
- Die Zuweisung ist global (kein Gremium-Scope), unbefristet, `granted_by=bootstrap` und
  **idempotent**: bereits vergebene Rollen werden nicht doppelt zugewiesen.
- Nach dem ersten erfolgreichen Admin-Login kann der Eintrag bleiben (no-op) oder über
  die normale RBAC-UI durch weitere Admins ersetzt werden.

## Profile

- **prod** — hinter NPM, externe Keycloak/SMTP/Nextcloud, ClamAV aktiv, **kein**
  Host-Port außer `web`. Aktiviert zusätzlich den `backup`-Service:
  ```bash
  docker compose --profile prod up -d --build
  ```
  Für das echte NPM-Netz im compose `proxy:` auf `external: true` umstellen.
- Default (ohne Profil) = Smoke-/Dev-Stack ohne `backup`.

## Backup & Restore

Tägliches verschlüsseltes Backup (PostgreSQL + MinIO, age) und die getestete
Restore-Prozedur: siehe [`backup/README.md`](backup/README.md). Restore-Test:
`../scripts/restore-smoke.sh`.

## Smoke-Test

```bash
../scripts/smoke.sh        # up + warten bis healthy
../scripts/smoke.sh down   # Stack inkl. Volumes abräumen
```

### Real-Stack-Smoke (Kernflüsse via HTTP/WS)

Fährt den vollen Stack hoch (Mock AUS, Bootstrap-Admin gesetzt) und prüft die
Kernflüsse rein über HTTP/WS — API up, `/api/health`, öffentlicher Branding-Read,
Auth-Pfad erreichbar (307), `/auth/me` 401, WS-Handshake erreichbar. Eigener
`COMPOSE_PROJECT_NAME` (berührt keinen anderen Stack); sichert/stellt ein
vorhandenes `deploy/.env` wieder her; räumt restlos ab.

```bash
../scripts/smoke-real-stack.sh                 # up -> Kernflüsse prüfen -> teardown
SMOKE_WEB_PORT=8090 ../scripts/smoke-real-stack.sh   # anderer Host-Port
```

CI: Job `real-stack-smoke` (opt-in wie e2e). Default-PR bleibt grün (skipped).
Triggern: `workflow_dispatch`, PR-Label `run-real-stack-smoke`, oder Repo-Variable
`RUN_REAL_STACK_SMOKE=true`. Kein FE-Selenium — das macht die Visual-Harness.
